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


def get_chunks_by_file_for_chatbot(chatbot_id: int, file_id: int):
    result = (
        supabase.table("knowledge_chunks")
        .select("*")
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
