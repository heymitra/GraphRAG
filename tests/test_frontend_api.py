import re
import tempfile
import unittest
from pathlib import Path

from graphrag_storage.file_storage import FileStorage
from frontend.app import app
from frontend.app import _single_file_input_pattern


class FrontendApiRegressionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app.testing = True
        cls.client = app.test_client()

    def get_json(self, path):
        response = self.client.get(path)
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        return response.get_json()

    def test_graph_items_keep_document_keys_with_graphrag_3_text_units(self):
        data = self.get_json('/api/data?mode=baseline')

        self.assertGreaterEqual(len(data['documents']), 1)
        self.assertGreaterEqual(len(data['entities']), 1)
        self.assertGreaterEqual(len(data['relationships']), 1)
        self.assertGreaterEqual(len(data['claims']), 1)

        for collection_name in ('entities', 'relationships', 'claims'):
            with self.subTest(collection=collection_name):
                self.assertTrue(
                    all(item.get('document_keys') for item in data[collection_name]),
                    f'{collection_name} should carry document_keys for filtering.',
                )

    def test_document_prompts_resolve_current_dataset_run_and_only_return_indexing_prompts(self):
        data = self.get_json('/api/document-prompts?mode=baseline&document_key=BrewBridge.txt')

        self.assertEqual(data['document']['title'], 'BrewBridge.txt')
        self.assertIn(data['record']['matched_via'], {'document', 'run'})
        self.assertGreaterEqual(len(data['entries']), 1)
        self.assertEqual({entry['category'] for entry in data['entries']}, {'Indexing'})
        self.assertEqual(
            {entry['key'] for entry in data['entries']},
            {
                'extract_graph',
                'summarize_descriptions',
                'extract_claims',
                'community_report_graph',
                'community_report_text',
            },
        )

    def test_umap_nodes_keep_document_keys(self):
        data = self.get_json('/api/umap?mode=auto_tuned')

        self.assertGreaterEqual(len(data['nodes']), 1)
        self.assertTrue(all(node.get('document_keys') for node in data['nodes']))

    def test_single_file_input_pattern_matches_uploaded_file_in_storage(self):
        pattern = _single_file_input_pattern('911Report-18-160').replace('$$', '$')

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / '911Report-18-160.txt').write_text('report body', encoding='utf-8')
            (root / '911Report-18-160-appendix.txt').write_text('appendix', encoding='utf-8')
            (root / 'other.txt').write_text('other body', encoding='utf-8')

            matches = list(FileStorage(base_dir=tmpdir).find(re.compile(pattern)))

        self.assertEqual(matches, ['911Report-18-160.txt'])


if __name__ == '__main__':
    unittest.main()
