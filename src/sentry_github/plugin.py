"""
sentry_github.plugin
~~~~~~~~~~~~~~~~~~~~

:copyright: (c) 2012 by the Sentry Team, see AUTHORS for more details.
:license: BSD, see LICENSE for more details.
"""
import requests
from django import forms
from django.utils.translation import ugettext_lazy as _
from sentry.plugins.bases.issue import IssuePlugin, NewIssueForm
from sentry.http import safe_urlopen, safe_urlread
from sentry.utils import json

import sentry_github


class GitHubOptionsForm(forms.Form):
    repo = forms.CharField(
        label=_('Repository Name'),
        widget=forms.TextInput(attrs={'placeholder': 'e.g. getsentry/sentry'}),
        help_text=_('Enter your repository name, including the owner.'))
    endpoint = forms.CharField(
        label=_('GitHub API Endpoint'),
        widget=forms.TextInput(attrs={'placeholder': 'https://api.github.com'}),
        initial='https://api.github.com',
        help_text=_('Enter the base URL to the GitHub API.'))
    github_url = forms.CharField(
        label=_('GitHub Base URL'),
        widget=forms.TextInput(attrs={'placeholder': 'https://github.com'}),
        initial='https://github.com',
        help_text=_('Enter the base URL to the GitHub for generating issue links.'))

    def clean_endpoint(self):
        data = self.cleaned_data['endpoint']
        return data.rstrip('/')

    def clean_github_url(self):
        data = self.cleaned_data['github_url']
        return data.rstrip('/')


class GitHubNewIssueForm(NewIssueForm):
    assignee = forms.ChoiceField(choices=tuple(), required=False)

    def __init__(self, assignee_choices, *args, **kwargs):
        super(GitHubNewIssueForm, self).__init__(*args, **kwargs)
        self.fields['assignee'].choices = assignee_choices


class GitHubPlugin(IssuePlugin):
    author = 'Sentry Team'
    author_url = 'https://github.com/getsentry/sentry'
    version = sentry_github.VERSION
    new_issue_form = GitHubNewIssueForm
    description = "Integrate GitHub issues by linking a repository to a project."
    resource_links = [
        ('Bug Tracker', 'https://github.com/getsentry/sentry-github/issues'),
        ('Source', 'https://github.com/getsentry/sentry-github'),
    ]

    slug = 'github'
    title = _('GitHub')
    conf_title = title
    conf_key = 'github'
    project_conf_form = GitHubOptionsForm
    auth_provider = 'github'

    def is_configured(self, request, project, **kwargs):
        return bool(self.get_option('repo', project))

    def get_new_issue_title(self, **kwargs):
        return 'Create GitHub Issue'

    def get_new_issue_read_only_fields(self, **kwargs):
        group = kwargs.get('group')
        if group:
            return [{'label': 'Github Repository', 'value': self.get_option('repo', group.project)}]
        return []

    def get_allowed_assignees(self, request, group):
        try:
            req = self.make_api_request(request, group, 'assignees')
            body = safe_urlread(req)
        except requests.RequestException:
            return tuple()

        try:
            json_resp = json.loads(body)
        except ValueError:
            return tuple()

        if req.status_code > 399:
            return tuple()

        users = tuple((u['login'], u['login']) for u in json_resp)

        return (('', 'Unassigned'),) + users

    def get_new_issue_form(self, request, group, event, **kwargs):
        """
        Return a Form for the "Create new issue" page.
        """
        return self.new_issue_form(self.get_allowed_assignees(request, group),
                                   request.POST or None,
                                   initial=self.get_initial_form_data(request, group, event))

    def make_api_request(self, request, group, github_api, json_data=None):
        auth = self.get_auth_for_user(user=request.user)
        if auth is None:
            raise forms.ValidationError(_('You have not yet associated GitHub with your account.'))

        repo = self.get_option('repo', group.project)
        endpoint = self.get_option('endpoint', group.project) or 'https://api.github.com'

        url = '%s/repos/%s/%s' % (endpoint, repo, github_api,)

        req_headers = {
            'Authorization': 'token %s' % auth.tokens['access_token'],
        }
        return safe_urlopen(url, json=json_data, headers=req_headers)

    def create_issue(self, request, group, form_data, **kwargs):
        # TODO: support multiple identities via a selection input in the form?
        json_data = {
            "title": form_data['title'],
            "body": form_data['description'],
            "assignee": form_data.get('assignee'),
        }

        try:
            req = self.make_api_request(request, group, 'issues', json_data=json_data)
            body = safe_urlread(req)
        except requests.RequestException as e:
            msg = unicode(e)
            raise forms.ValidationError(_('Error communicating with GitHub: %s') % (msg,))

        try:
            json_resp = json.loads(body)
        except ValueError as e:
            msg = unicode(e)
            raise forms.ValidationError(_('Error communicating with GitHub: %s') % (msg,))

        if req.status_code > 399:
            raise forms.ValidationError(json_resp['message'])

        return json_resp['number']

    def get_issue_label(self, group, issue_id, **kwargs):
        return 'GH-%s' % issue_id

    def get_issue_url(self, group, issue_id, **kwargs):
        # XXX: get_option may need tweaked in Sentry so that it can be pre-fetched in bulk
        repo = self.get_option('repo', group.project)
        github_url = self.get_option('github_url', group.project) or 'https://github.com'

        return '%s/%s/issues/%s' % (github_url, repo, issue_id)
