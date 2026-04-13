import json
import os

from rest_framework import viewsets, status
from rest_framework.response import Response
from rest_framework.views import APIView
from .models import Author, Book, Member, Loan
from .serializers import AuthorSerializer, BookSerializer, MemberSerializer, LoanSerializer
from rest_framework.decorators import action
from django.utils import timezone
from .tasks import send_loan_notification, build_backlink_graph, BACKLINK_GRAPH_PATH
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


class BacklinkGraphView(APIView):
    """GET /api/backlinks/

    Serves the backlink graph produced by :func:`library.tasks.build_backlink_graph`.
    If the graph file does not yet exist, POST (or ``?build=1``) triggers the task.

    Query params:
      - target: return only the backlinks for a single target host
      - limit:  cap the number of target entries returned (default 100)
    """

    def get(self, request):
        if not os.path.exists(BACKLINK_GRAPH_PATH):
            if request.query_params.get('build') == '1':
                build_backlink_graph.delay()
                return Response(
                    {'status': 'Backlink graph build scheduled. Try again shortly.'},
                    status=status.HTTP_202_ACCEPTED,
                )
            return Response(
                {
                    'error': 'Backlink graph has not been generated yet.',
                    'hint': 'POST to this endpoint or GET with ?build=1 to schedule the task.',
                },
                status=status.HTTP_404_NOT_FOUND,
            )

        with open(BACKLINK_GRAPH_PATH, 'r', encoding='utf-8') as fp:
            data = json.load(fp)

        graph = data.get('backlinks', {})
        target = request.query_params.get('target')
        if target:
            return Response(
                {
                    'target': target,
                    'sources': graph.get(target, []),
                    'generated_at': data.get('generated_at'),
                }
            )

        try:
            limit = int(request.query_params.get('limit', 100))
        except ValueError:
            limit = 100
        limit = max(1, min(limit, 10000))

        items = list(graph.items())[:limit]
        return Response(
            {
                'generated_at': data.get('generated_at'),
                'source': data.get('source'),
                'node_count': data.get('node_count'),
                'edge_count': data.get('edge_count'),
                'records_processed': data.get('records_processed'),
                'returned': len(items),
                'backlinks': dict(items),
            }
        )

    def post(self, request):
        async_result = build_backlink_graph.delay()
        return Response(
            {'status': 'Backlink graph build scheduled.', 'task_id': async_result.id},
            status=status.HTTP_202_ACCEPTED,
        )
