# -*- coding: utf-8 -*- vim:fileencoding=utf-8:
# Copyright (C) 2010-2014 GRNET S.A.
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
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
from django.conf.urls import patterns, include, url
from django.conf import settings

from django.contrib import admin
from django_markdown import flatpages

# import urls
from accounts import urls as accounts
from gnt.urls import graphs, instances, jobs, clusters, nodegroup
from stats import urls as stats_urls
from apply.urls import application, user
from gnt.views import discovery
from notifications import urls as notifications
from auditlog import urls as auditlog
admin.autodiscover()
flatpages.register()

urlpatterns = patterns(
    '',
    (r'^setlang/?$', 'django.views.i18n.set_language'),
    url(r'^$', 'gnt.views.user_index', name="user-instances"),
    url(r'^news/?$', 'gnt.views.news', name="news"),

    # unique, helper urls
    url(r'^clearcache/?$', 'gnt.views.clear_cache', name="clearcache"),
    url(r'^operating_systems/$', discovery.get_operating_systems, name='operating_systems_json'),
    url(r'^tagusergrps/?$', 'gnt.views.get_user_groups', name="tagusergroups"),

    # mount apps
    (r'^application/', include(application)),
    (r'^history/', include(auditlog)),
    (r'^nodegroups/', include(nodegroup)),
    (r'^notifications/', include(notifications)),
    (r'^user/', include(user)),
    (r'^stats/', include(stats_urls)),
    (r'^jobs/', include(jobs)),
    (r'^cluster/', include(clusters)),
    (r'^instances/', include(instances)),
    (r'^accounts/', include(accounts)),
    (r'^graph/', include(graphs)),
    # get a list of the available operating systems
    url(r'^markdown/', include('django_markdown.urls')),
    (r'^admin/', include(admin.site.urls)),
)

if settings.DEBUG:
    urlpatterns += patterns('',
        (r'^static/(?P<path>.*)', 'django.views.static.serve',\
            {'document_root':  settings.STATIC_URL}),
    )

