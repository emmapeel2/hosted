# -*- coding: utf-8 -*-
#
# Copyright © 2012 - 2019 Michal Čihař <michal@cihar.com>
#
# This file is part of Weblate <https://weblate.org/>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.
#

from __future__ import unicode_literals

import json
import os.path
import subprocess

from django.conf import settings
from django.core.mail import EmailMessage
from django.core.serializers.json import DjangoJSONEncoder
from django.shortcuts import redirect
from django.utils.translation import ugettext as _, ugettext_lazy

from fakturace.storage import InvoiceStorage

import thepay.config
import thepay.gateApi
import thepay.dataApi
import thepay.payment

from wlhosted.payments.models import Payment

BACKENDS = {}


def get_backend(name):
    backend = BACKENDS[name]
    if backend.debug and not settings.PAYMENT_DEBUG:
        raise KeyError('Invalid backend')
    return backend


def list_backends():
    result = []
    for backend in BACKENDS.values():
        if not backend.debug or settings.PAYMENT_DEBUG:
            result.append(backend)
    return sorted(result, key=lambda x: x.name)


class InvalidState(ValueError):
    pass


def register_backend(backend):
    BACKENDS[backend.name] = backend
    return backend


class Backend(object):
    name = None
    debug = False
    verbose = None
    description = ''
    recurring = False

    def __init__(self, payment):
        select = Payment.objects.filter(pk=payment.pk).select_for_update()
        self.payment = select[0]
        self.invoice = None

    def perform(self, request, back_url, complete_url):
        """Performs payment and optionally redirects user."""
        raise NotImplementedError()

    def collect(self, request):
        """Collects payment information."""
        raise NotImplementedError()

    def initiate(self, request, back_url, complete_url):
        """Initiates payment and optionally redirects user."""
        if self.payment.state != Payment.NEW:
            raise InvalidState()

        if self.payment.repeat and not self.recurring:
            raise InvalidState()

        result = self.perform(request, back_url, complete_url)

        # Update payment state
        self.payment.state = Payment.PENDING
        self.payment.backend = self.name
        self.payment.save()

        return result

    def complete(self, request):
        """Payment completion called from returned request."""
        if self.payment.state != Payment.PENDING:
            raise InvalidState()

        status = self.collect(request)
        if status is None:
            return False
        if status:
            self.success()
            return True
        self.failure()
        return False

    def generate_invoice(self):
        """Generates an invoice."""
        if settings.PAYMENT_FAKTURACE is None:
            return
        storage = InvoiceStorage(settings.PAYMENT_FAKTURACE)
        customer = self.payment.customer
        customer_id = 'web-{}'.format(customer.pk)
        contact_file = storage.update_contact(
            customer_id,
            customer.name,
            customer.address,
            customer.city,
            customer.country.name,
            customer.email,
            customer.tax if customer.tax else '',
            customer.vat if customer.vat else '',
            'EUR',
            'weblate',
        )
        invoice_file = storage.create(
            customer_id,
            0,
            rate='{:f}'.format(self.payment.amount_without_vat),
            item=self.payment.description,
            vat=str(customer.vat_rate),
            payment_method=self.description,
            category=self.payment.extra.get('category', 'weblate'),
            payment_id=str(self.payment.pk),
        )
        invoice = storage.get(invoice_file)
        invoice.write_tex()
        invoice.build_pdf()
        invoice.mark_paid(
            json.dumps(self.payment.details, indent=2, cls=DjangoJSONEncoder)
        )

        self.payment.invoice = invoice.invoiceid

        # Commit to git
        subprocess.run(
            [
                'git', 'add',
                '--',
                contact_file,
                invoice_file,
                invoice.tex_path,
                invoice.pdf_path,
                invoice.paid_path,
            ],
            check=True,
            cwd=settings.PAYMENT_FAKTURACE,
        )
        subprocess.run(
            [
                'git', 'commit',
                '-m', 'Invoice {}'.format(self.payment.invoice),
            ],
            check=True,
            cwd=settings.PAYMENT_FAKTURACE,
        )
        self.invoice = invoice

    def notify_user(self):
        """Send email notification with an invoice."""
        email = EmailMessage(
            _('Your payment on weblate.org'),
            _('''Hello

Thank you for your payment on weblate.org.

You will find an invoice for this payment attached.
Alternatively you can download it from the website:

%s
''') % self.payment.customer.origin,
            'billing@weblate.org',
            [self.payment.customer.email],
        )
        if self.invoice is not None:
            with open(self.invoice.pdf_path, 'rb') as handle:
                email.attach(
                    os.path.basename(self.invoice.pdf_path),
                    handle.read(),
                    'application/pdf'
                )
        email.send()

    def notify_failure(self):
        """Send email notification with a failure."""
        email = EmailMessage(
            _('Your payment on weblate.org failed'),
            _('''Hello

Your payment on weblate.org has failed.

%s

Retry issuing the payment on the website:

%s

If concerning a recurring payment, it is retried three times,
and if still failing, cancelled.
''') % (self.payment.details.get('reject_reason', 'Uknown'), self.payment.customer.origin),
            'billing@weblate.org',
            [self.payment.customer.email],
        )
        if self.invoice is not None:
            with open(self.invoice.pdf_path, 'rb') as handle:
                email.attach(
                    os.path.basename(self.invoice.pdf_path),
                    handle.read(),
                    'application/pdf'
                )
        email.send()

    def success(self):
        self.payment.state = Payment.ACCEPTED
        if not self.recurring:
            self.payment.recurring = ''

        self.generate_invoice()
        self.payment.save()

        self.notify_user()

    def failure(self):
        self.payment.state = Payment.REJECTED
        self.payment.save()

        self.notify_failure()


@register_backend
class DebugPay(Backend):
    name = 'pay'
    debug = True
    verbose = 'Pay'
    description = 'Paid (TEST)'
    recurring = True

    def perform(self, request, back_url, complete_url):
        return None

    def collect(self, request):
        return True


@register_backend
class DebugReject(DebugPay):
    name = 'reject'
    verbose = 'Reject'
    description = 'Reject (TEST)'
    recurring = False

    def collect(self, request):
        self.payment.details['reject_reason'] = 'Debug reject'
        return False


@register_backend
class DebugPending(DebugPay):
    name = 'pending'
    verbose = 'Pending'
    description = 'Pending (TEST)'
    recurring = False

    def perform(self, request, back_url, complete_url):
        return redirect('https://cihar.com/?url=' + complete_url)

    def collect(self, request):
        return True


@register_backend
class ThePayCard(Backend):
    name = 'thepay-card'
    verbose = ugettext_lazy('Payment card')
    description = 'Payment Card (The Pay)'
    recurring = True
    thepay_method = 21

    def __init__(self, payment):
        super().__init__(payment)
        self.config = thepay.config.Config()
        if settings.PAYMENT_THEPAY_MERCHANTID:
            self.config.setCredentials(
                settings.PAYMENT_THEPAY_MERCHANTID,
                settings.PAYMENT_THEPAY_ACCOUNTID,
                settings.PAYMENT_THEPAY_PASSWORD,
                settings.PAYMENT_THEPAY_DATAAPI
            )

    def perform(self, request, back_url, complete_url):
        if self.payment.repeat:
            api = thepay.gateApi.GateApi(self.config)
            try:
                api.cardCreateRecurrentPayment(
                    str(self.payment.repeat.pk),
                    str(self.payment.pk),
                    self.payment.vat_amount,
                )
            except thepay.gateApi.GateError as error:
                self.payment.details = {'errorDescription': error.args[0]}
                # Failure is handled in collect using API
            return None

        payment = thepay.payment.Payment(self.config)

        payment.setCurrency('EUR')
        payment.setValue(self.payment.vat_amount)
        payment.setMethodId(self.thepay_method)
        payment.setCustomerEmail(self.payment.customer.email)
        payment.setDescription(self.payment.description)
        payment.setReturnUrl(complete_url)
        payment.setMerchantData(str(self.payment.pk))
        if self.payment.recurring:
            payment.setIsRecurring(1)
        return redirect(payment.getCreateUrl())

    def collect(self, request):
        if self.payment.repeat:
            data = thepay.dataApi.DataApi(self.config)
            payment = data.getPayments(
                merchant_data=str(self.payment.pk)
            ).payments.payment[0]
            self.payment.details = dict(payment)
            status = int(payment.state)
        else:
            return_payment = thepay.payment.ReturnPayment(self.config)
            return_payment.parseData(request.GET)

            # Check params signature
            try:
                return_payment.checkSignature()
            except thepay.payment.ReturnPayment.InvalidSignature:
                return False

            # Check we got correct payment
            if return_payment.getMerchantData() != str(self.payment.pk):
                return False

            # Store payment details
            self.payment.details = dict(return_payment.data)

            status = return_payment.getStatus()

        if status == 2:
            return True
        if status == 7:
            return None
        reason = 'Unknown: {}'.format(status)
        if status == 3:
            reason = _('Payment cancelled')
        elif status == 4:
            reason = _('Payment error')
        elif status == 6:
            reason = 'Underpaid'
        elif status == 9:
            reason = 'Deposit confirmed'
        self.payment.details['reject_reason'] = reason
        return False


@register_backend
class ThePayBitcoin(ThePayCard):
    name = 'thepay-bitcoin'
    verbose = ugettext_lazy('Bitcoin')
    description = 'Bitcoin (The Pay)'
    recurring = False
    thepay_method = 29
