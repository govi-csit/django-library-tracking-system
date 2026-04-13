from datetime import timedelta

from django.contrib.auth.models import User
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from .models import Author, Book, Loan, Member


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
