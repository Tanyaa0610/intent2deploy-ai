
from app.services.rag.indexer import index_repository
from app.services.rag.retriever import retrieve


def test_index_demo_repository_produces_real_chunks(demo_repo_copy):
    stats = index_repository(demo_repo_copy, "test_collection_indexing")
    assert stats.file_count > 5
    assert stats.chunk_count > stats.file_count  # multiple chunks per file on average
    assert ".env" not in stats.indexed_files


def test_retrieval_changes_with_different_queries(demo_repo_copy):
    index_repository(demo_repo_copy, "test_collection_retrieval")

    auth_results = retrieve("test_collection_retrieval", "password reset authentication", top_k=5)
    orders_results = retrieve("test_collection_retrieval", "order total null reference bug", top_k=5)

    auth_files = {r.file for r in auth_results}
    orders_files = {r.file for r in orders_results}

    assert "src/auth/service.py" in auth_files
    assert "src/orders/service.py" in orders_files
    # Different queries must not return identical top results (proves
    # retrieval is not hardcoded/static).
    assert auth_files != orders_files
