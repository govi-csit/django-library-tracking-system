from datetime import timedelta

from django.contrib.auth.models import User
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from .models import Author, Book, Loan, Member
from .tasks import check_overdue_loans


class ExtendDueDateTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='alice', password='pw')
        self.member = Member.objects.create(user=self.user)
        self.author = Author.objects.create(first_name='Jane', last_name='Doe')
        self.book = Book.objects.create(
            title='Test Book',
            author=self.author,
            isbn='1234567890123',
            genre='fiction',
            available_copies=1,
        )
        self.loan = Loan.objects.create(book=self.book, member=self.member)

    def _url(self, loan_id):
        return reverse('loan-extend-due-date', kwargs={'pk': loan_id})

    def test_extend_due_date_happy_path(self):
        original_due = self.loan.due_date
        response = self.client.post(
            self._url(self.loan.id), {'additional_days': 7}, format='json'
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.loan.refresh_from_db()
        self.assertEqual(self.loan.due_date, original_due + timedelta(days=7))
        self.assertEqual(response.data['due_date'], str(self.loan.due_date))

    def test_extend_due_date_rejects_non_positive(self):
        response = self.client.post(
            self._url(self.loan.id), {'additional_days': 0}, format='json'
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_extend_due_date_rejects_overdue_loan(self):
        self.loan.due_date = timezone.now().date() - timedelta(days=1)
        self.loan.save()
        response = self.client.post(
            self._url(self.loan.id), {'additional_days': 3}, format='json'
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


class TopActiveMembersTests(APITestCase):
    def setUp(self):
        self.author = Author.objects.create(first_name='A', last_name='B')
        self.book = Book.objects.create(
            title='T', author=self.author, isbn='9999999999999',
            genre='fiction', available_copies=100,
        )
        self.members = []
        for i in range(6):
            user = User.objects.create_user(username=f'u{i}', password='pw')
            member = Member.objects.create(user=user)
            self.members.append(member)
            for _ in range(i):  # 0..5 active loans
                Loan.objects.create(book=self.book, member=member)

    def test_top_active_returns_top_five(self):
        response = self.client.get(reverse('member-top-active'))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 5)
        counts = [row['active_loans'] for row in response.data]
        self.assertEqual(counts, sorted(counts, reverse=True))
        self.assertEqual(counts[0], 5)


@override_settings(
    EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
    DEFAULT_FROM_EMAIL='library@test.local',
    CELERY_TASK_ALWAYS_EAGER=True,
)
class CheckOverdueLoansTaskTests(TestCase):
    def setUp(self):
        self.author = Author.objects.create(first_name='A', last_name='B')
        self.book = Book.objects.create(
            title='Overdue Book', author=self.author,
            isbn='1112223334445', genre='fiction', available_copies=10,
        )
        self.today = timezone.now().date()

    def _make_loan(self, username, email, due_date, is_returned=False):
        user = User.objects.create_user(username=username, password='pw', email=email)
        member = Member.objects.create(user=user)
        loan = Loan.objects.create(book=self.book, member=member)
        Loan.objects.filter(pk=loan.pk).update(due_date=due_date, is_returned=is_returned)
        loan.refresh_from_db()
        return loan

    def test_sends_email_only_for_overdue_unreturned_loans(self):
        overdue = self._make_loan('over', 'over@test.local', self.today - timedelta(days=3))
        self._make_loan('future', 'future@test.local', self.today + timedelta(days=5))
        self._make_loan('returned', 'returned@test.local',
                        self.today - timedelta(days=2), is_returned=True)

        result = check_overdue_loans()

        self.assertEqual(result, 'Notified: 1 overdue loans')
        self.assertEqual(len(mail.outbox), 1)
        msg = mail.outbox[0]
        self.assertEqual(msg.to, ['over@test.local'])
        self.assertIn('Overdue Book', msg.body)
        self.assertIn(str(overdue.due_date), msg.body)
        self.assertEqual(msg.subject, 'Overdue Book Reminder')

    def test_no_emails_when_nothing_overdue(self):
        self._make_loan('ok', 'ok@test.local', self.today + timedelta(days=1))
        result = check_overdue_loans()
        self.assertEqual(result, 'Notified: 0 overdue loans')
        self.assertEqual(len(mail.outbox), 0)

    def test_skips_members_without_email(self):
        self._make_loan('noemail', '', self.today - timedelta(days=1))
        result = check_overdue_loans()
        self.assertEqual(result, 'Notified: 0 overdue loans')
        self.assertEqual(len(mail.outbox), 0)
