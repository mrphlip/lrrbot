import asyncio
import unittest

import lrrbot.cardviewer

class TestCardViewerExtract(unittest.TestCase):
	def setUp(self):
		self.cardviewer = lrrbot.cardviewer.CardViewer(None, asyncio.get_event_loop())

	def test_extract_gatherer(self):
		self.assertEqual(self.cardviewer._extract("http://gatherer.wizards.com/Handlers/Image.ashx?multiverseid=368490&type=card"), 368490)

	def test_extract_local_dash(self):
		self.assertEqual(self.cardviewer._extract("http://localhost/cards/ISD-92.jpg"), ("ISD", "92"))

	def test_extract_local_dash_double_faced(self):
		self.assertEqual(self.cardviewer._extract("http://localhost/cards/SOI-5a.jpg"), ("SOI", "5a"))

	def test_extract_local_dash_set_code_with_underscore(self):
		self.assertEqual(self.cardviewer._extract("http://localhost/cards/DD3_JVC-1.jpg"), ("DD3_JVC", "1"))

	def test_extract_local_underscore(self):
		self.assertEqual(self.cardviewer._extract("http://localhost/cards/ISD_92.jpg"), ("ISD", "92"))

	def test_extract_local_underscore_double_faced(self):
		self.assertEqual(self.cardviewer._extract("http://localhost/cards/SOI_5a.jpg"), ("SOI", "5a"))

	def test_extract_local_underscore_set_code_with_underscore(self):
		self.assertEqual(self.cardviewer._extract("http://localhost/cards/DD3_JVC_1.jpg"), ("DD3_JVC", "1"))

	def test_extract_local_dash_leading_zeroes(self):
		self.assertEqual(self.cardviewer._extract("http://localhost/cards/SOI-005a.jpg"), ("SOI", "5a"))

	def test_extract_local_underscore_leading_zeroes(self):
		self.assertEqual(self.cardviewer._extract("http://localhost/cards/SOI_005a.jpg"), ("SOI", "5a"))
