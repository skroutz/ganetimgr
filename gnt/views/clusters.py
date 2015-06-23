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

import json
from gevent.pool import Pool

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.urlresolvers import reverse
from django.contrib.messages import constants as msgs
from django.contrib import messages
from django.contrib.auth.models import User
from django.core.cache import cache
from django.db import close_connection
from django.http import (
    HttpResponse,
    HttpResponseRedirect,
    HttpResponseServerError
)
from django.shortcuts import get_object_or_404, render
from django.views.decorators.csrf import csrf_exempt

from util.client import GanetiApiError

from gnt.utils import refresh_cluster_cache, prepare_clusternodes, \
        clusterdetails_generator

from auditlog.utils import auditlog_entry

from gnt.models import Cluster, InstanceAction, Instance


@login_required
def clusternodes_json(request, cluster=None):
    if (
        request.user.is_superuser or
        request.user.has_perm('gnt.view_instances')
    ):
        nodedetails = []
        jresp = {}
        nodes = None
        nodes = cache.get('allclusternodes')
        bad_clusters = cache.get('badclusters')
        bad_nodes = cache.get('badnodes')
        if nodes is None:
            nodes, bad_clusters, bad_nodes = prepare_clusternodes()
            cache.set('allclusternodes', nodes, 90)
        if bad_clusters:
            messages.add_message(
                request,
                msgs.WARNING,
                "Some nodes may be missing because the" +
                " following clusters are unreachable: " +
                ", ".join([c.description for c in bad_clusters])
            )
            cache.set('badclusters', bad_clusters, 90)
        if bad_nodes:
            messages.add_message(
                request,
                msgs.ERROR,
                "Some nodes appear to be offline: " +
                ", ".join(bad_nodes)
            )
            cache.set('badnodes', bad_nodes, 90)
        if cluster:
            try:
                cluster = Cluster.objects.get(hostname=cluster)
            except Cluster.DoesNotExist:
                cluster = None
        for node in nodes:
            if not cluster or (cluster and node['cluster'] == cluster.slug):
                node_dict = {}
                node_dict['name'] = node['name']
                # node_dict['node_group'] = node['node_group']
                node_dict['mem_used'] = node['mem_used']
                node_dict['mfree'] = node['mfree']
                node_dict['mtotal'] = node['mtotal']
                node_dict['shared_storage'] = node['shared_storage']
                node_dict['disk_used'] = node['disk_used']
                node_dict['dfree'] = node['dfree']
                node_dict['dtotal'] = node['dtotal']
                node_dict['ctotal'] = node['ctotal']
                node_dict['pinst_cnt'] = node['pinst_cnt']
                node_dict['pinst_list'] = node['pinst_list']
                node_dict['role'] = node['role']
                if cluster:
                    node_dict['cluster'] = cluster.hostname
                else:
                    node_dict['cluster'] = node['cluster']
                nodedetails.append(node_dict)
        jresp['aaData'] = nodedetails
        res = jresp
        return HttpResponse(json.dumps(res), content_type='application/json')
    else:
        return HttpResponse(
            json.dumps({'error': 'Unauthorized access'}),
            content_type='application/json'
        )


@login_required
def instance_popup(request):
    if (
        request.user.is_superuser or
        request.user.has_perm('gnt.view_instances')
    ):
        if request.method == 'GET':
            if 'cluster' in request.GET:
                cluster_slug = request.GET.get('cluster')
            if 'instance' in request.GET:
                instance = request.GET.get('instance')
        cluster = get_object_or_404(Cluster, slug=cluster_slug)
        instance = cluster.get_instance_or_404(instance)

        return render(
            request,
            'instances/instance_popup.html',
            {
                'cluster': cluster,
                'instance': instance
            }
        )
    else:
        return HttpResponseRedirect(reverse('user-instances'))


@login_required
def get_clusternodes(request):
    if (
        request.user.is_superuser or
        request.user.has_perm('gnt.view_instances')
    ):
        nodes = cache.get('allclusternodes')
        bad_clusters = cache.get('badclusters')
        bad_nodes = cache.get('badnodes')
        if nodes is None:
            nodes, bad_clusters, bad_nodes = prepare_clusternodes()
            cache.set('allclusternodes', nodes, 90)
        if bad_clusters:
            messages.add_message(
                request,
                msgs.WARNING,
                "Some nodes may be missing because the" +
                " following clusters are unreachable: " +
                ", ".join([c.description for c in bad_clusters])
            )
            cache.set('badclusters', bad_clusters, 90)
        if bad_nodes:
            messages.add_message(
                request,
                msgs.ERROR,
                "Some nodes appear to be offline: " +
                ", ".join(bad_nodes)
            )
            cache.set('badnodes', bad_nodes, 90)
        if settings.SERVER_MONITORING_URL:
            servermon_url = settings.SERVER_MONITORING_URL
        status_dict = {}
        status_dict['offline'] = 0
        status_dict['regular'] = 0
        status_dict['drained'] = 0
        status_dict['master'] = 0
        status_dict['candidate'] = 0
        for n in nodes:
            if n['role'] == 'O':
                status_dict['offline'] += 1
            if n['role'] == 'D':
                status_dict['drained'] += 1
            if n['role'] == 'R':
                status_dict['regular'] += 1
            if n['role'] == 'C':
                status_dict['candidate'] += 1
            if n['role'] == 'M':
                status_dict['master'] += 1
        clusters = list(set([n['cluster'] for n in nodes]))
        return render(
            request,
            'clusters/cluster_nodes.html',
            {
                'nodes': nodes,
                'clusters': clusters,
                'statuses': status_dict,
                'servermon': servermon_url
            }
        )
    else:
        return HttpResponseRedirect(reverse('user-instances'))


@login_required
@csrf_exempt
def reinstalldestreview(request, application_hash, action_id):
    action_id = int(action_id)
    instance = None
    if action_id not in [1, 2, 3, 4]:
        return HttpResponseRedirect(reverse('user-instances'))
    # Normalize before trying anything with it.
    activation_key = application_hash.lower()
    try:
        action = InstanceAction.objects.get(
            activation_key=activation_key,
            action=action_id
        )
    except InstanceAction.DoesNotExist:
        activated = True
        return render(
            request,
            'instances/verify_action.html',
            {
                'action': action_id,
                'activated': activated,
                'instance': instance,
                'hash': application_hash
            }
        )
    instance = action.instance
    cluster = action.cluster
    action_value = action.action_value
    activated = False
    try:
        instance_object = Instance.objects.get(name=instance)
    except Instance.DoesNotExist:
        # This should occur only when user changes email
        pass
    if action.activation_key_expired():
        activated = True
    if request.method == 'POST':
        if not activated:
            instance_action = InstanceAction.objects.activate_request(
                application_hash
            )
            if not instance_action:
                return render(
                    request,
                    'instances/verify_action.html',
                    {
                        'action': action_id,
                        'activated': activated,
                        'instance': instance,
                        'hash': application_hash
                    }
                )
            if action_id in [1, 2, 3]:
                auditlog = auditlog_entry(request, "", instance, cluster.slug, save=False)
            if action_id == 1:
                auditlog.update(action="Reinstall")
                jobid = cluster.reinstall_instance(instance, instance_action)
                # in case there is no selected os
                if jobid:
                    auditlog.update(job_id=jobid)
                else:
                    return HttpResponseServerError()
            if action_id == 2:
                auditlog.update(action="Destroy")
                jobid = cluster.destroy_instance(instance)
                auditlog.update(job_id=jobid)
            if action_id == 3:
                # As rename causes cluster lock we perform some cache
                # engineering on the cluster instances,
                # nodes and the users cache
                refresh_cluster_cache(cluster, instance)
                auditlog.update(action="Rename to %s" % action_value)
                jobid = cluster.rename_instance(instance, action_value)
                auditlog.update(job_id=jobid)
            if action_id == 4:
                user = User.objects.get(username=request.user)
                user.email = action_value
                user.save()
                return HttpResponseRedirect(reverse('profile'))
            activated = True
            return HttpResponseRedirect(reverse('user-instances'))
        else:
            return render(
                request,
                'instances/verify_action.html',
                {
                    'action': action_id,
                    'activated': activated,
                    'instance': instance,
                    'instance_object': instance_object,
                    'hash': application_hash
                }
            )
    elif request.method == 'GET':
        return render(
            request,
            'instances/verify_action.html',
            {
                'instance': instance,
                'instance_object': instance_object,
                'action': action_id,
                'action_value': action_value,
                'cluster': cluster,
                'activated': activated,
                'hash': application_hash
            }
        )
    else:
        return HttpResponseRedirect(reverse('user-instances'))


@login_required
def clusterdetails(request):
    if request.user.is_superuser or request.user.has_perm('gnt.view_instances'):
        return render(
            request,
            'clusters/clusters.html',
            {'clusters': Cluster.objects.all()}
        )
    else:
        return HttpResponseRedirect(reverse('user-instances'))


@login_required
def clusterdetails_json(request):
    if request.user.is_superuser or request.user.has_perm('gnt.view_instances'):
        clusterlist = cache.get("cluster:allclusterdetails")
        if clusterlist is None:
            clusterlist = []
            errors = []
            p = Pool(10)

            def _get_cluster_details(cluster):
                try:
                    clusterlist.append(clusterdetails_generator(cluster.slug))
                except (GanetiApiError, Exception):
                    errors.append(Exception)
                finally:
                    close_connection()
            p.map(_get_cluster_details, Cluster.objects.all())
            cache.set("clusters:allclusterdetails", clusterlist, 180)
        return HttpResponse(json.dumps(clusterlist),
                            content_type='application/json')
    else:
        return HttpResponse(
            json.dumps({'error': "Unauthorized access"}),
            content_type='application/json'
        )

