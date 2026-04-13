from celery import shared_task
from .models import Loan
from django.core.mail import send_mail
from django.conf import settings
from django.utils import timezone
import logging
logger = logging.getLogger(__name__)

@shared_task
def send_loan_notification(loan_id):
    try:
        loan = Loan.objects.get(id=loan_id)
        member_email = loan.member.user.email
        book_title = loan.book.title
        send_mail(
            subject='Book Loaned Successfully',
            message=f'Hello {loan.member.user.username},\n\nYou have successfully loaned "{book_title}".\nPlease return it by the due date.',
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[member_email],
            fail_silently=False,
        )
    except Loan.DoesNotExist:
        logger.error(f'No loan with id {loan_id}')
        raise


@shared_task
def check_overdue_loans(loan_id):
    try:
        today = timezone.now().date()
        overdue_loans = Loan.objects.filter(
            is_returned=False,
            due_date__lt=today,
        ).select_related('member__user', 'book')

        for loan in overdue_loans:
            member_email = loan.member.user.email
            book_title = loan.book.title
            due_date = loan.due_date

            send_mail(
                subject='Overdue Book Reminder',
                message=f'{book_title} is due on "{due_date}".\nPlease return it asap',
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[member_email],
                fail_silently=False,
            )

            return f"Notfied: {overdue_loans.count()} overdue loans"
    except Loan.DoesNotExist:
        pass
