import datetime
from unittest import TestCase as UnitTestCase

from nose.plugins.skip import SkipTest

from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from django.test import TestCase, TransactionTestCase

from nosedjangotests.polls.models import Poll, Choice

def _test_using_content_types(self):
    p1, _ = Poll.objects.get_or_create(
        question='Who you?', pub_date=datetime.datetime.now())

    choice1 = Choice(poll=p1, choice='me')
    choice1.save()

def _test_get_contenttypes(self):
    models = [Poll, Choice]

    for model in models:
        content_type = ContentType.objects.get_for_model(model)

        # Make sure this isn't just using the cache
        ct_db = ContentType.objects.get(pk=content_type.pk)
        for attr in ['name', 'app_label', 'model']:
            self.assertEqual(
                getattr(ct_db, attr), getattr(content_type, attr))

def _test_permissions(self):
    perm_types = ['add', 'change', 'delete']
    models = [(Poll, 'poll'), (Choice, 'choice')]

    for model, name in models:
        for perm_type in perm_types:
            codename = '%s_%s' % (perm_type, name)
            content_type = ContentType.objects.get_for_model(model)
            num_perms = Permission.objects.filter(
                codename=codename, content_type=content_type).count()
            self.assertEqual(num_perms, 1)

class DjangoTestCase(TestCase):

    def test_a_skip(self):
        raise SkipTest('Skipping')

    def test_using_content_types_1(self):
        _test_using_content_types(self)

    def test_get_contenttypes_1(self):
        _test_get_contenttypes(self)

    def test_permissions_1(self):
        _test_permissions(self)

    def test_using_content_types_2(self):
        _test_using_content_types(self)

    def test_get_contenttypes_2(self):
        _test_get_contenttypes(self)

    def test_permissions_2(self):
        _test_permissions(self)

class DjangoTransactionTestCase(TestCase):

    def test_a_skip(self):
        raise SkipTest('Skipping')

    def test_using_content_types_1(self):
        _test_using_content_types(self)

    def test_get_contenttypes_1(self):
        _test_get_contenttypes(self)

    def test_permissions_1(self):
        _test_permissions(self)

    def test_using_content_types_2(self):
        _test_using_content_types(self)

    def test_get_contenttypes_2(self):
        _test_get_contenttypes(self)

    def test_permissions_2(self):
        _test_permissions(self)

class WithTransactionUnitTestCase(UnitTestCase):

    def test_a_skip(self):
        raise SkipTest('Skipping')

    def test_using_content_types_1(self):
        _test_using_content_types(self)

    def test_get_contenttypes_1(self):
        _test_get_contenttypes(self)

    def test_permissions_1(self):
        _test_permissions(self)

    def test_using_content_types_2(self):
        _test_using_content_types(self)

    def test_get_contenttypes_2(self):
        _test_get_contenttypes(self)

    def test_permissions_2(self):
        _test_permissions(self)

class NoTransactionUnitTestCase(UnitTestCase):
    use_transaction_isolation = False

    def test_a_skip(self):
        raise SkipTest('Skipping')

    def test_using_content_types_1(self):
        _test_using_content_types(self)

    def test_get_contenttypes_1(self):
        _test_get_contenttypes(self)

    def test_permissions_1(self):
        _test_permissions(self)

    def test_using_content_types_2(self):
        _test_using_content_types(self)

    def test_get_contenttypes_2(self):
        _test_get_contenttypes(self)

    def test_permissions_2(self):
        _test_permissions(self)

