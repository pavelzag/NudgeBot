# -*- coding: utf-8 -*-
from datetime import timedelta, datetime
import json
import re

import dateparser
import requests

from . import env
from config import config
from common import ExtendedEnum
from __builtin__ import classmethod


class PRtag(ExtendedEnum):
    NOTEST = 'NOTEST'
    NOMERGE = 'NOMERGE'
    LP1 = '1LP'
    LP2 = '2LP'
    LP3 = '3LP'


class PRstate(ExtendedEnum):
    WIP = 'WIP'
    BLOCKED = 'BLOCKED'
    WIPTEST = 'WIPTEST'
    RFR = 'RFR'


class PullRequestTag(object):
    """Represents Pull Request title tag.
    e.g. [RFR], [WIP], ...
    """

    @classmethod
    def fetch(cls, title):
        """PullRequestTitleTag Factory - fetching tags from title.
        Args:
            * title (str): the Pull request title.
        Returns: list of PullRequestTitleTag
        """
        assert isinstance(title, basestring)
        detected_tags = []
        tag_names = re.findall(config().config.github.pull_request_title_tag.pattern, title)
        for tag_name in tag_names:
            tag_name = tag_name.upper()
            if tag_name in PRtag.values():
                tag = PRtag.get_by_value(tag_name)
            elif tag_name in PRstate.values():
                tag = PRstate.get_by_value(tag_name)
            else:
                raise Exception()  # TODO: Define appropriate exception
            detected_tags.append(cls(tag))
        return detected_tags

    def __init__(self, tag):
        assert isinstance(tag, (PRtag, PRstate))
        self._tag = tag

    def __eq__(self, other):
        return self._tag == getattr(other, '_tag', None)

    def __repr__(self, *args, **kwargs):
        return '<{} type="{}" name="{}">'.format(
            self.__class__.__name__, self.type, self.name)

    @property
    def type(self):
        return self._tag.__class__

    @property
    def name(self):
        return self._tag.value

    @property
    def raw(self):
        return config().config.github.pull_request_title_tag.format.format(self.name)

    @property
    def json(self):
        return {'type': self.type, 'name': self.name, 'raw': self.raw}


class PullRequest(object):
    """Pull Request includes a bunch of the properties and the information
    about the pull request.
    """
    def __init__(self, repo, json_data):

        self.repo = repo
        self._pr_handler = json_data

    @classmethod
    def get_all(cls, **filters):
        """
        Args (filters):
            * state (optional): (str) the state of the pull requests to grab (open || closed).
            * logins (optional): (list || tuple) a list of the logins.
            * repos (optional): (list || tuple) a list of the repos.
        """
        state = filters.get('state', 'open')
        logins = [login.lower() for login in filters.get('logins', [])]
        repos = filters.get('repos', env().repos)
        prs = []
        for repo in repos:
            for pr in repo.get_pulls(state=state):
                if logins and pr.user.login.lower() not in logins:
                    continue
                prs.append(cls(repo, pr))
        return prs

    def judge(self):
        lrc = self.last_review_comment
        if not lrc:
            return
        pr_inactivity_timeout = timedelta(config().config.github.pr_inactivity_timeout.days,
                                          config().config.github.pr_inactivity_timeout.hours)
        pr_inactivity_time = datetime.now() - lrc.created_at
        if pr_inactivity_time > pr_inactivity_timeout:
            return ('PR#{} is waiting for review for {} days and {} hours: {}'
                    .format(self.number, pr_inactivity_time.days,
                            pr_inactivity_time.seconds / 3600, self.url))

    @property
    def state_history(self):
        # TODO: Returns: {<date>: <state>, ...}
        pass

    @property
    def json_data(self):
        return self._pr_handler

    @property
    def url(self):
        return self.json_data.url

    @property
    def html(self):
        return requests.get(self._pr_handler.html_url).content

    @property
    def patch_url(self):
        return self._pr_handler.patch_url

    @property
    def diff_url(self):
        return self._pr_handler.diff_url

    @property
    def patch(self):
        return requests.get(self._pr_handler.patch_url).content.encode('UTF-8')

    @property
    def diff(self):
        return requests.get(self._pr_handler.diff_url).content.encode('UTF-8')

    @property
    def number(self):
        return self._pr_handler.number

    @property
    def user(self):
        return getattr(self._pr_handler.user, 'name',
                       self._pr_handler.user.login)

    @property
    def title(self):
        return self._pr_handler.title

    @property
    def tags(self):
        return PullRequestTag.fetch(self.title)

    @tags.setter
    def tags(self, tags):
        """Setting the tags <tags> to the pull request title
        """
        if len(set([t.type for t in tags]).union()) != len(tags):
            raise Exception()  # TODO: Implement multiple tags with the same type exception
        return self._pr_handler.edit(
            '{} {}'.format(
                ''.join([t.raw for t in tags]), re.split(
                    config().config.github.pull_request_title_tag.pattern, self.title
                    )[-1].strip()
            )
        )

    @tags.deleter
    def tags(self):
        return self._pr_handler.edit(
            re.split(config().config.github.pull_request_title_tag.pattern, self.title)[-1].strip())

    @property
    def age(self):
        now = datetime.now()
        return now - self._pr_handler.created_at

    @property
    def review_comments(self):
        comments = [c for c in self._pr_handler.get_review_comments()]
        comments.sort(key=lambda c: c.updated_at)
        return comments

    @property
    def last_review_comment(self):
        review_comments = self.review_comments
        if review_comments:
            return max(review_comments, key=lambda item: item.updated_at)

    @property
    def comments(self):
        comments = [c for c in self._pr_handler.get_issue_comments()]
        comments.sort(key=lambda c: c.updated_at)
        return comments

    @property
    def test_results(self):
        tests = json.loads(requests.get(self._pr_handler.raw_data['statuses_url']).content)
        out = {}
        for test in tests:
            out[test['context']] = test['description']
        return out

    @property
    def owner(self):
        return self._pr_handler.user

    @property
    def last_code_update(self):
        return dateparser.parse(list(self._pr_handler.get_commits()).pop().last_modified)

    @property
    def json(self):
        """Get the object data as dictionary"""
        lst_cmnt = self.last_review_comment
        age_total_seconds = int(self.age.total_seconds())
        days_ago = age_total_seconds / 86400
        hours_ago = (age_total_seconds - days_ago * 86400) / 3600
        out = {
            'repo': self.repo.name,
            'number': self.number,
            'owner': self.owner.name or self.owner.login,
            'title': self.title,
            'tags': [tag.json for tag in self.tags],
            'age': {
                'days': days_ago,
                'hours': hours_ago
            },
            'tests': self.test_results,
            'last_code_update': self.last_code_update.isoformat()
        }
        if lst_cmnt:
            out['last_review_comment'] = {
                'user': lst_cmnt.user.name or lst_cmnt.user.login,
                'body': lst_cmnt.body,
                'updated_at': lst_cmnt.updated_at.isoformat()
            }
        return out