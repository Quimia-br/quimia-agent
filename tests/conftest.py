"""Isola o LangSmith: testes não enviam traces nem usam banco operacional."""

import copy
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from langsmith.utils import LangSmithNotFoundError

from app.observability import storage


class FakeLangSmith:
    def __init__(self):
        self.runs = {}
        self.feedbacks = {}
        self.project_id = uuid4()
        self.queries = 0

    def create_run(self, **kwargs):
        data = copy.deepcopy(kwargs)
        data['id'] = UUID(str(data['id']))
        data['session_id'] = self.project_id
        self.runs[str(data['id'])] = SimpleNamespace(**data)

    def list_runs(self, **kwargs):
        self.queries += 1
        rows = [run for run in self.runs.values() if not getattr(run, 'parent_run_id', None)
                and run.project_name == kwargs['project_name'] and storage.TAG in run.tags
                and run.start_time >= kwargs['start_time']]
        return iter(sorted(rows, key=lambda run: run.start_time, reverse=True)[:kwargs.get('limit', len(rows))])

    def read_run(self, run_id):
        try:
            return self.runs[str(run_id)]
        except KeyError:
            raise LangSmithNotFoundError('run missing') from None

    def read_project(self, **kwargs):
        return SimpleNamespace(id=self.project_id)

    def list_feedback(self, *, run_ids, feedback_key):
        return iter([f for f in self.feedbacks.values() if str(f.run_id) in run_ids and f.key in feedback_key])

    def read_feedback(self, feedback_id):
        try:
            return self.feedbacks[str(feedback_id)]
        except KeyError:
            raise LangSmithNotFoundError('feedback missing') from None

    def create_feedback(self, **kwargs):
        self.feedbacks[str(kwargs['feedback_id'])] = SimpleNamespace(
            **kwargs, modified_at=datetime.now(timezone.utc))

    def update_feedback(self, feedback_id, *, score):
        feedback = self.feedbacks[str(feedback_id)]
        feedback.score = score
        feedback.modified_at = datetime.now(timezone.utc)


@pytest.fixture(autouse=True)
def isolated_sre_storage(monkeypatch):
    fake = FakeLangSmith()
    monkeypatch.setenv('LANGSMITH_TRACING', 'false')
    monkeypatch.setenv('LANGSMITH_API_KEY', 'test-only')
    monkeypatch.setenv('LANGSMITH_PROJECT', 'quimia-test')
    monkeypatch.setattr(storage, 'get_client', lambda: fake)
    monkeypatch.setattr(storage, 'enabled', lambda: True)
    monkeypatch.setattr(storage, 'flush', lambda: None)
    storage._cache.clear()
    yield fake
    storage._cache.clear()
