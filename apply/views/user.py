import datetime

from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User, Group
from django.contrib.sites.models import Site
from django.conf import settings
from django.core.urlresolvers import reverse
from django.core.mail import send_mail
from django.http import (
    HttpResponseRedirect,
    HttpResponseForbidden,
    HttpResponse
)
from django.shortcuts import render, get_object_or_404
from django.template.loader import render_to_string, get_template
from django.template.context import RequestContext
from django.utils.safestring import mark_safe
from django.utils.translation import ugettext_lazy as _

from ganeti.models import InstanceAction

from apply.forms import EmailChangeForm, NameChangeForm, SshKeyForm, OrganizationPhoneChangeForm
from apply.utils import check_mail_change_pending
from apply.models import SshPublicKey


@login_required
def user_info(request, type, usergroup):
    if (
        request.user.is_superuser or
        request.user.has_perm('ganeti.view_instances')
    ):
        if type == 'user':
            usergroup_info = User.objects.get(username=usergroup)
        if type == 'group':
            usergroup_info = Group.objects.get(name=usergroup)
        return render(
            request,
            'users/user_info.html',
            {'usergroup': usergroup_info, 'type': type}
        )
    else:
        return HttpResponseRedirect(reverse('user-instances'))


@login_required
def idle_accounts(request):
    if (
        request.user.is_superuser or
        request.user.has_perm('ganeti.view_instances')
    ):
        idle_users = []
        idle_users.extend([
            u for u in User.objects.filter(
                is_active=True,
                last_login__lte=datetime.datetime.now() - datetime.timedelta(
                    days=int(settings.IDLE_ACCOUNT_NOTIFICATION_DAYS)
                )
            ) if u.email
        ])
        idle_users = list(set(idle_users))
        return render(
            request,
            'users/idle_accounts.html',
            {'users': idle_users},
        )


@login_required
def profile(request):
    return render(
        request,
        'users/profile.html',
        {}
    )


@login_required
def mail_change(request):
    changed = False
    pending = False
    usermail = request.user.email
    if request.method == "GET":
        form = EmailChangeForm()
        pending = check_mail_change_pending(request.user)
    elif request.method == "POST":
        form = EmailChangeForm(request.POST)
        if form.is_valid():
            usermail = form.cleaned_data['email1']
            user = User.objects.get(username=request.user)
            if user.email:
                mailchangereq = InstanceAction.objects.create_action(
                    request.user,
                    '',
                    None,
                    4,
                    usermail
                )
                fqdn = Site.objects.get_current().domain
                url = "https://%s%s" % (
                    fqdn,
                    reverse(
                        "reinstall-destroy-review",
                        kwargs={
                            'application_hash': mailchangereq.activation_key,
                            'action_id': 4
                        }
                    )
                )
                email = render_to_string(
                    "reinstall_mail.txt",
                    {
                        "user": request.user,
                        "action": mailchangereq.get_action_display(),
                        "action_value": mailchangereq.action_value,
                        "url": url
                    }
                )
                send_mail(
                    "%sUser email change requested" % (
                        settings.EMAIL_SUBJECT_PREFIX
                    ),
                    email,
                    settings.SERVER_EMAIL,
                    [request.user.email]
                )
                pending = True
            else:
                user.email = usermail
                user.save()
                changed = True
                form = EmailChangeForm()
    return render(
        request,
        "users/mail_change.html",
        {
            'mail': usermail,
            'form': form,
            'changed': changed,
            'pending': pending
        }
    )


@login_required
def name_change(request):
    changed = False
    user_full_name = request.user.get_full_name()
    if request.method == "GET":
        form = NameChangeForm()
    elif request.method == "POST":
        form = NameChangeForm(request.POST)
        if form.is_valid():
            user_name = form.cleaned_data['name']
            user_surname = form.cleaned_data['surname']
            user = User.objects.get(username=request.user)
            user.first_name = user_name
            user.last_name = user_surname
            user.save()
            changed = True
            user_full_name = user.get_full_name()
            form = NameChangeForm()
    return render(
        request,
        'users/name_change.html',
        {
            'name': user_full_name,
            'form': form,
            'changed': changed
        }
    )


@login_required
def other_change(request):
    changed = False
    if request.method == "GET":
        form = OrganizationPhoneChangeForm(instance=request.user.profile)
    elif request.method == "POST":
        form = OrganizationPhoneChangeForm(request.POST, instance=request.user.profile)
        if form.is_valid():
            form.save()
            changed = True
    return render(
        request,
        'users/other_change.html',
        {
            'form': form,
            'changed': changed
        }
    )


@login_required
def user_keys(request):
    msg = None
    if request.method == "GET":
        form = SshKeyForm()
    else:
        form = SshKeyForm(request.POST)
        if form.is_valid():
            dups = []
            for key_type, key, comment in form.cleaned_data["ssh_pubkey"]:
                ssh_key = SshPublicKey(key_type=key_type, key=key,
                                       comment=comment, owner=request.user)
                fprint = ssh_key.compute_fingerprint()
                other_keys = SshPublicKey.objects.filter(owner=request.user,
                                                         fingerprint=fprint)
                if not other_keys:
                    ssh_key.fingerprint = fprint
                    ssh_key.save()
                    form = SshKeyForm()
                else:
                    dups.append(fprint)
            if dups:
                msg = _("The following keys were skipped because"
                        " they already exist:<br />%s") % "<br />".join(dups)
                msg = mark_safe(msg)

    keys = SshPublicKey.objects.filter(owner=request.user)
    return render(
        request,
        'users/user_keys.html',
        {
            'form': form,
            'keys': keys,
            'msg': msg
        }
    )


@login_required
def delete_key(request, key_id):
    key = get_object_or_404(SshPublicKey, pk=key_id)
    if key.owner != request.user:
        t = get_template("403.html")
        return HttpResponseForbidden(content=t.render(RequestContext(request)))
    key.delete()
    return HttpResponseRedirect(reverse("user-keys"))


@login_required
def pass_notify(request):
    user = User.objects.get(username=request.user)
    user.profile.force_logout()
    if user.email:
        email = render_to_string(
            "users/emails/pass_change_notify_mail.txt",
            {"user": request.user}
        )
        send_mail(
            "%sUser password change" % (settings.EMAIL_SUBJECT_PREFIX),
            email,
            settings.SERVER_EMAIL,
            [request.user.email]
        )
        return HttpResponse("mail sent", mimetype="text/plain")
    else:
        return HttpResponse("mail not sent", mimetype="text/plain")
