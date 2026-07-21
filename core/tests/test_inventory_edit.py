"""Inventory items can be edited and deleted (not just added)."""
from django.test import Client, TestCase
from django.urls import reverse

from core.models import InventoryItem
from core.tests.factory import build_world, PASSWORD


class InventoryEditTests(TestCase):
    def setUp(self):
        self.w = build_world()
        self.c = Client()
        self.c.login(username='admin1', password=PASSWORD)
        self.item = InventoryItem.objects.create(
            name='Chalk', category='Supplies', quantity=10, reorder_level=5)

    def test_add_item(self):
        self.c.post(reverse('inventory'), {
            'action': 'add', 'name': 'Markers', 'category': 'Stationery',
            'quantity': '20', 'reorder_level': '4'})
        self.assertTrue(InventoryItem.objects.filter(name='Markers', quantity=20).exists())

    def test_edit_item(self):
        self.c.post(reverse('inventory'), {
            'action': 'edit', 'id': self.item.id, 'name': 'Chalk Box',
            'category': 'Supplies', 'quantity': '3', 'reorder_level': '5',
            'unit': 'box'})
        self.item.refresh_from_db()
        self.assertEqual(self.item.name, 'Chalk Box')
        self.assertEqual(self.item.quantity, 3)
        self.assertEqual(self.item.unit, 'box')
        self.assertTrue(self.item.low)   # 3 <= 5

    def test_delete_item(self):
        self.c.post(reverse('inventory'), {'action': 'delete', 'id': self.item.id})
        self.assertFalse(InventoryItem.objects.filter(id=self.item.id).exists())

    def test_edit_bad_id_is_safe(self):
        r = self.c.post(reverse('inventory'), {
            'action': 'edit', 'id': 99999, 'name': 'x', 'quantity': '1'})
        self.assertEqual(r.status_code, 302)   # no crash, just redirects
