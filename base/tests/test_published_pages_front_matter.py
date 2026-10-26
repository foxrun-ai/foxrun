#!/usr/bin/env python3
"""The generated glossary pages carry SCHEMA front matter (T742); GUIDE and INSTALL are hand-written."""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from base import published_pages


class PublishedFrontMatterTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix='published-pages-')
        self.addCleanup(temp.cleanup)
        self.home, self.portfolio = Path(temp.name) / 'home', Path(temp.name) / 'portfolio'
        (self.home / 'config').mkdir(parents=True)
        self.portfolio.mkdir()
        (self.home / 'config/words.tsv').write_text(
            'workspace\tgroup\tword\tmeaning\twhere\tsource\nsystem\tWords\tBase\tBuilds the database.\t\tT742\n')

    def test_each_page_starts_with_one_block_and_a_rebuild_keeps_the_timestamp(self):
        first = published_pages.pages(self.home, self.portfolio)
        body = first[self.home / 'GLOSSARY.md']
        self.assertTrue(body.startswith('---\ntype: glossary\nworkspace: system\ntimestamp: '))
        self.assertEqual(body.count('\n---\n'), 1)
        (self.home / 'GLOSSARY.md').write_text(body)
        self.assertEqual(first, published_pages.pages(self.home, self.portfolio))

    def test_guide_and_install_are_not_generated(self):
        products = published_pages.pages(self.home, self.portfolio)
        self.assertNotIn(self.home / 'GUIDE.md', products)
        self.assertNotIn(self.home / 'INSTALL.md', products)

    def test_local_words_show_and_a_linked_workspace_is_skipped(self):
        shop = self.portfolio / 'shop'
        (shop / 'config').mkdir(parents=True)
        (shop / 'GLOSSARY.md').write_text('old\n')
        (shop / 'config/glossary-words.tsv').write_text('word\tmeaning\tgroup\tsource\nTrail\tThe shown slice.\tShop words\tT742\n')
        (shop / 'config/glossary-context.md').write_text('---\ntype: note\nworkspace: shop\n---\nShop context.\n')
        (self.portfolio / 'shop-alias').symlink_to('shop')
        products = published_pages.pages(self.home, self.portfolio)
        self.assertIn('| Trail | The shown slice. |  | T742 |', products[shop / 'GLOSSARY.md'])
        self.assertIn('Shop context.', products[shop / 'GLOSSARY.md'])
        self.assertNotIn('\n---\ntype: note', products[shop / 'GLOSSARY.md'])
        self.assertEqual(products[shop / 'GLOSSARY.md'].count('\n---\n'), 1)
        self.assertNotIn(self.portfolio / 'shop-alias/GLOSSARY.md', products)

    def test_shipped_agent_meaning_uses_a_shipped_seat_and_the_page_matches_its_source(self):
        tree = Path(__file__).resolve().parents[2]
        with tempfile.TemporaryDirectory() as empty:
            products = published_pages.pages(tree, Path(empty))
        shipped = (tree / 'GLOSSARY.md').read_text(encoding='utf-8')
        self.assertEqual(products[tree / 'GLOSSARY.md'], shipped)
        agent = next(line for line in shipped.splitlines() if line.startswith('| Agent |'))
        self.assertIn('(e.g. the Keeper)', agent)
        self.assertNotIn('mack', agent.lower())


if __name__ == '__main__':
    unittest.main()
