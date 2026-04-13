from rest_framework import viewsets, status
from rest_framework.response import Response
from .models import Author, Book, Member, Loan
from .serializers import AuthorSerializer, BookSerializer, MemberSerializer, LoanSerializer
from rest_framework.decorators import action
from django.utils import timezone
from .tasks import send_loan_notification
from django.db import transaction
from django.db.models import F


class AuthorViewSet(viewsets.ModelViewSet):
    queryset = Author.objects.all()
    serializer_class = AuthorSerializer

class BookViewSet(viewsets.ModelViewSet):
    queryset = Book.objects.all()
    serializer_class = BookSerializer

    @action(detail=True, methods=['post'])
    def loan(self, request, pk=None):
        with transaction.atomic():



            book = Book.objects.select_for_update().get(pk=pk)
            if book.available_copies < 1:
                return Response({'error': 'No available copies.'}, status=status.HTTP_400_BAD_REQUEST)
            member_id = request.data.get('member_id')
            try:
                member = Member.objects.get(id=member_id)
            except Member.DoesNotExist:
                return Response({'error': 'Member does not exist.'}, status=status.HTTP_400_BAD_REQUEST)

            existing_loan = Loan.objects.filter(book=book, member=member, is_returned=False).exists()
            if existing_loan:
                return Response({'error': 'Book already loaned.'}, status=status.HTTP_400_BAD_REQUEST)

            loan = Loan.objects.create(book=book, member=member)

            Book.objects.filter(pk=book.pk, available_copies__gt=0).update(available_copies=F('available_copies')-1)
            book.save()
            send_loan_notification.delay(loan.id)
            return Response({'status': 'Book loaned successfully.'}, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['post'])
    def return_book(self, request, pk=None):
        book = self.get_object()
        member_id = request.data.get('member_id')
        try:
            loan = Loan.objects.get(book=book, member__id=member_id, is_returned=False)
        except Loan.DoesNotExist:
            return Response({'error': 'Active loan does not exist.'}, status=status.HTTP_400_BAD_REQUEST)
        loan.is_returned = True
        loan.return_date = timezone.now().date()
        loan.save()
        book.available_copies += 1
        book.save()
        return Response({'status': 'Book returned successfully.'}, status=status.HTTP_200_OK)

class MemberViewSet(viewsets.ModelViewSet):
    queryset = Member.objects.all()
    serializer_class = MemberSerializer

class LoanViewSet(viewsets.ModelViewSet):
    queryset = Loan.objects.all()
    serializer_class = LoanSerializer
