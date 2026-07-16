"""Pagination helper for views that build their list in Python rather than
via a single .paginate()-able query (e.g. results aggregated per-student
across many rows, or a list requiring a full-table pass like dedup before
it's final). Mimics Flask-SQLAlchemy's Pagination interface so it works
with the same pagination nav template block used everywhere else in the app.
"""


class ListPagination:
    def __init__(self, items, page, per_page, total):
        self.page = max(1, page)
        self.per_page = per_page
        self.total = total
        self.pages = max(1, (total + per_page - 1) // per_page)
        start = (self.page - 1) * per_page
        self.items = items[start:start + per_page]
        self.has_prev = self.page > 1
        self.has_next = self.page < self.pages
        self.prev_num = self.page - 1
        self.next_num = self.page + 1

    def iter_pages(self, left_edge=1, right_edge=1, left_current=2, right_current=2):
        last = 0
        for p in range(1, self.pages + 1):
            if (p <= left_edge or p > self.pages - right_edge
                    or (self.page - left_current <= p <= self.page + right_current)):
                if last + 1 != p:
                    yield None
                yield p
                last = p


def paginate_list(items, page, per_page=50):
    return ListPagination(items, page, per_page, len(items))
