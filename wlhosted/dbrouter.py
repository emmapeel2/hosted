# -*- coding: utf-8 -*-
#
# Copyright © 2012 - 2018 Michal Čihař <michal@cihar.com>
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

class HostedRouter(object):
    """
    A router to send wlhosted app to separate database and
    block running migrations on that.
    """
    def db_for_read(self, model, **hints):
        """
        Attempts to read wlhosted models go to hosted_db.
        """
        if model._meta.app_label == 'wlhosted':
            return 'hosted_db'
        return None

    def db_for_write(self, model, **hints):
        """
        Attempts to write wlhosted models go to hosted_db.
        """
        if model._meta.app_label == 'wlhosted':
            return 'hosted_db'
        return None

    def allow_migrate(self, db, app_label, model_name=None, **hints):
        """
        Make sure the auth app only appears in the 'hosted_db'
        database.
        """
        if app_label == 'wlhosted':
            return db == 'hosted_db'
        elif db == 'hosted_db':
            return False
        return None