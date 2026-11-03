"""Offline regression tests for approved-event opening-hour monitoring."""
import unittest
from datetime import date
from unittest.mock import patch
import herold_zeiten_bestaetigt as monitor

class RecheckTests(unittest.TestCase):
    def setUp(self):
        self.day=date(2026,11,3)
        self.event={"name":"Mittelaltermarkt Bremgarten","city":"Bremgarten",
                    "start":"2027-10-22","end":"2027-10-24",
                    "website":"https://example.org/event"}
        self.row={"event_id":"approved-1","status":"approved","event":self.event}
        # Force this record into today's rotating batch.
        self.day=next(date(2026,11,d) for d in range(1,8)
            if sum(b"approved-1")%7==date(2026,11,d).toordinal()%7)

    def test_no_hours_from_generic_weekday_text(self):
        html="<p>Sonntag 10:00-17:00</p>"
        self.assertEqual(monitor.scan([self.row],[],self.day,lambda url:html),[])

    def test_explicit_year_and_day_jsonld(self):
        html='''<script type="application/ld+json">{"@type":"Event","name":"Mittelaltermarkt Bremgarten","startDate":"2027-10-24T10:00:00","endDate":"2027-10-24T17:00:00"}</script>'''
        result=monitor.scan([self.row],[],self.day,lambda url:html)
        self.assertEqual(len(result),1)
        self.assertEqual(result[0]["dailyHours"],[{"date":"2027-10-24","open":"10:00","close":"17:00"}])
        self.assertEqual(result[0]["status"],"pending")

    def test_approved_hours_are_never_overwritten(self):
        event={**self.event,"dailyHours":[{"date":"2027-10-24","open":"09:00","close":"18:00"}]}
        row={**self.row,"event":event}
        self.assertEqual(monitor.scan([row],[],self.day,lambda url:"bad"),[])

    def test_old_year_does_not_match(self):
        html='''<script type="application/ld+json">{"@type":"Event","name":"Mittelaltermarkt Bremgarten","startDate":"2026-10-25T10:00:00","endDate":"2026-10-25T17:00:00"}</script>'''
        self.assertEqual(monitor.scan([self.row],[],self.day,lambda url:html),[])

    def test_existing_proposal_survives_later_search(self):
        proposal={"event_id":"approved-1","status":"pending","start":"2027-10-22","end":"2027-10-24","dailyHours":[{"date":"2027-10-24","open":"10:00","close":"17:00"}]}
        self.assertEqual(monitor.scan([self.row],[proposal],self.day,lambda url:""),[proposal])

if __name__=="__main__":
    unittest.main()
