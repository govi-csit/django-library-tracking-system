from celery import shared_task
from .models import Loan
from django.core.mail import send_mail
from django.conf import settings
from django.utils import timezone
import logging
import gzip
import json
import os
from collections import defaultdict
from urllib.parse import urljoin, urlparse

logger = logging.getLogger(__name__)

BACKLINK_GRAPH_PATH = os.path.join(settings.BASE_DIR, 'data', 'backlink_graph.json')
WAT_FILE_PATH = os.path.join(settings.BASE_DIR, 'data', 'sample.wat.gz')


def _iter_warc_records(fp):
    while True:
        line = fp.readline()
        if not line:
            return
        if line.strip() != b'WARC/1.0':
            continue
        headers = {}
        while True:
            h = fp.readline()
            if not h or h in (b'\r\n', b'\n'):
                break
            key, sep, val = h.partition(b':')
            if sep:
                headers[key.strip().decode('utf-8', 'replace')] = val.strip().decode('utf-8', 'replace')
        length = int(headers.get('Content-Length', '0') or 0)
        body = fp.read(length) if length else b''
        fp.read(4)  # trailing CRLFCRLF between records
        yield headers, body


def _host_of(url):
    try:
        return urlparse(url).netloc.lower() or None
    except Exception:
        return None


@shared_task
def build_backlink_graph(wat_path=None):
    """Parse a Common Crawl WAT file and build a host-level backlink graph.

    The resulting mapping is {target_host: [source_host, ...]} — for each host,
    the list of hosts that have at least one anchor (<a href>) pointing to it.
    Result is written to data/backlink_graph.json and returned as a summary.
    """
    path = wat_path or WAT_FILE_PATH
    backlinks = defaultdict(set)
    records_seen = 0
    edges = 0

    with gzip.open(path, 'rb') as fp:
        for headers, body in _iter_warc_records(fp):
            if headers.get('WARC-Type') != 'metadata':
                continue
            if 'application/json' not in headers.get('Content-Type', ''):
                continue
            source_uri = headers.get('WARC-Target-URI')
            if not source_uri:
                continue
            try:
                payload = json.loads(body)
            except (ValueError, UnicodeDecodeError):
                continue
            records_seen += 1
            html_meta = (
                payload.get('Envelope', {})
                .get('Payload-Metadata', {})
                .get('HTTP-Response-Metadata', {})
                .get('HTML-Metadata', {})
            )
            links = html_meta.get('Links') or []
            source_host = _host_of(source_uri)
            if not source_host:
                continue
            for link in links:
                path_attr = link.get('path', '')
                if not path_attr.startswith('A@'):
                    continue
                raw = link.get('url', '')
                if not raw or raw.startswith('javascript:') or raw.startswith('#'):
                    continue
                absolute = urljoin(source_uri, raw)
                target_host = _host_of(absolute)
                if not target_host or target_host == source_host:
                    continue
                if source_host not in backlinks[target_host]:
                    backlinks[target_host].add(source_host)
                    edges += 1

    graph = {tgt: sorted(srcs) for tgt, srcs in backlinks.items()}
    os.makedirs(os.path.dirname(BACKLINK_GRAPH_PATH), exist_ok=True)
    with open(BACKLINK_GRAPH_PATH, 'w', encoding='utf-8') as out:
        json.dump(
            {
                'generated_at': timezone.now().isoformat(),
                'source': os.path.basename(path),
                'records_processed': records_seen,
                'edge_count': edges,
                'node_count': len(graph),
                'backlinks': graph,
            },
            out,
        )
    logger.info('Backlink graph built: %d nodes, %d edges', len(graph), edges)
    return {'nodes': len(graph), 'edges': edges, 'records_processed': records_seen}

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
