from app.database.db import supabase

# 1. CREATE (Insert)
def save_knowledge_chunk(chatbot_id: int, file_id: int, content: str, embedding: list, metadata: dict = {}):
    data = {
        "chatbot_id": chatbot_id,
        "file_id": file_id,
        "content": content,
        "embedding": embedding,
        "metadata": metadata
    }
    result = supabase.table("knowledge_chunks").insert(data).execute()
    return result.data[0]

# 2. READ (Select)
def get_chunks_by_file(file_id: int):
    result = (
        supabase.table("knowledge_chunks")
        .select("*")
        .eq("file_id", file_id)
        .execute()
    )
    return result.data

# 3. UPDATE
def update_chunk_metadata(chunk_id: int, new_metadata: dict):
    result = (
        supabase.table("knowledge_chunks")
        .update({"metadata": new_metadata})
        .eq("id", chunk_id)
        .execute()
    )
    return result.data[0]

# 4. DELETE
def delete_chunks_by_file(file_id: int):
    result = (
        supabase.table("knowledge_chunks")
        .delete()
        .eq("file_id", file_id)
        .execute()
    )
    return result.data


def delete_chunks_by_file_for_chatbot(chatbot_id: int, file_id: int):
    result = (
        supabase.table("knowledge_chunks")
        .delete()
        .eq("chatbot_id", chatbot_id)
        .eq("file_id", file_id)
        .execute()
    )
    return result.data


CHUNK_FIELDS_WITHOUT_EMBEDDING = "id,chatbot_id,file_id,content,metadata,created_at"


def publish_knowledge_rows(chatbot_id):
    """Stream the primary/supporting documents, chunks, and graph facts read by retrieval."""
    page_size = 200

    def pages(table, fields, order, filter_query=None):
        offset = 0
        while True:
            # PostgREST builders accumulate limit and offset parameters. Start fresh each time.
            query = supabase.table(table).select(",".join(fields)).eq("chatbot_id", chatbot_id)
            if filter_query:
                query = filter_query(query)
            for field in order:
                query = query.order(field)
            rows = query.range(offset, offset + page_size - 1).execute().data
            if rows:
                yield rows
            if len(rows) < page_size:
                return
            offset += len(rows)

    file_fields = ("id", "is_active", "is_enabled", "file_type", "file_name", "created_at")
    files = pages("knowledge_files", file_fields, ("id",),
                  lambda query: query.or_("is_active.eq.true,is_enabled.eq.true,is_enabled.is.null"))
    for sources in files:
        for row in sources:
            yield ("file", row)
        file_ids = [row["id"] for row in sources]
        chunks = pages("knowledge_chunks", ("id", "file_id", "content"), ("id",),
                       lambda query: query.in_("file_id", file_ids))
        for rows in chunks:
            for row in rows:
                yield ("chunk", row)

    # Graph RAG reads facts across this bot, including facts attached to non-primary files.
    for table, fields in (("knowledge_graph_nodes", ("name",)),
                          ("knowledge_graph_edges", ("source_name", "target_name", "rel_type"))):
        for rows in pages(table, fields, fields):
            for row in rows:
                yield (table, row)


def get_chunks_by_file_for_chatbot(chatbot_id: int, file_id: int, include_embedding: bool = True):
    """Load every chunk of one file.

    ``include_embedding=False`` drops the vector column. It is ~10 KB of JSON
    per chunk and dominates the response: a typical 44-chunk file measured
    474 KB / 635 ms with it and 52 KB / 256 ms without, from the deployed
    machine. Callers that only keyword-match on ``content`` should pass False;
    similarity search already runs server-side in search_similar_chunks.
    """
    result = (
        supabase.table("knowledge_chunks")
        .select("*" if include_embedding else CHUNK_FIELDS_WITHOUT_EMBEDDING)
        .eq("chatbot_id", chatbot_id)
        .eq("file_id", file_id)
        .execute()
    )
    return result.data or []


# 5. SEARCH (Vector Similarity)
def search_similar_chunks(
    chatbot_id: int,
    query_embedding: list,
    match_threshold: float = 0.5,
    match_count: int = 5,
    file_id: int = None
):
    if file_id:
        result = supabase.rpc(
            "match_knowledge_chunks_by_file",
            {
                "query_embedding": query_embedding,
                "match_threshold": match_threshold,
                "match_count": match_count,
                "p_chatbot_id": chatbot_id,
                "p_file_id": file_id
            }
        ).execute()
    else:
        result = supabase.rpc(
            "match_knowledge_chunks",
            {
                "query_embedding": query_embedding,
                "match_threshold": match_threshold,
                "match_count": match_count,
                "p_chatbot_id": chatbot_id
            }
        ).execute()

    return result.data
