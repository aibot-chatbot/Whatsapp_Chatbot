import logging
from app.database.db import supabase

def upsert_node(chatbot_id: int, file_id: int, name: str, label: str, properties: dict = None):
    if properties is None:
        properties = {}
    data = {
        "chatbot_id": chatbot_id,
        "file_id": file_id,
        "name": name.strip().lower(),
        "label": label.strip(),
        "properties": properties
    }
    try:
        result = (
            supabase.table("knowledge_graph_nodes")
            .upsert(data, on_conflict="chatbot_id,name")
            .execute()
        )
        return result.data[0] if result.data else None
    except Exception as e:
        logging.error(f"Failed to upsert node {name}: {e}")
        return None

def upsert_edge(chatbot_id: int, file_id: int, source_name: str, target_name: str, rel_type: str, properties: dict = None):
    if properties is None:
        properties = {}
    
    source = source_name.strip().lower()
    target = target_name.strip().lower()
    
    # Do not allow self-referencing relationships
    if source == target:
        return None
        
    data = {
        "chatbot_id": chatbot_id,
        "file_id": file_id,
        "source_name": source,
        "target_name": target,
        "rel_type": rel_type.strip().upper().replace(" ", "_"),
        "properties": properties
    }
    try:
        result = (
            supabase.table("knowledge_graph_edges")
            .upsert(data, on_conflict="chatbot_id,source_name,target_name,rel_type")
            .execute()
        )
        return result.data[0] if result.data else None
    except Exception as e:
        logging.error(f"Failed to upsert edge {source} -> {target}: {e}")
        return None

def get_edges_for_nodes(chatbot_id: int, node_names: list):
    if not node_names:
        return []
    
    normalized_names = [name.strip().lower() for name in node_names if name.strip()]
    if not normalized_names:
        return []
        
    try:
        # Retrieve edges starting from our matched nodes
        result_source = (
            supabase.table("knowledge_graph_edges")
            .select("*")
            .eq("chatbot_id", chatbot_id)
            .in_("source_name", normalized_names)
            .execute()
        )
        # Retrieve edges pointing to our matched nodes
        result_target = (
            supabase.table("knowledge_graph_edges")
            .select("*")
            .eq("chatbot_id", chatbot_id)
            .in_("target_name", normalized_names)
            .execute()
        )
        
        seen = set()
        combined = []
        for edge in (result_source.data or []) + (result_target.data or []):
            edge_key = (edge["source_name"], edge["target_name"], edge["rel_type"])
            if edge_key not in seen:
                seen.add(edge_key)
                combined.append(edge)
        return combined
    except Exception as e:
        logging.error(f"Failed to get edges for nodes {node_names}: {e}")
        return []

def get_graph_data(chatbot_id: int):
    try:
        nodes_result = (
            supabase.table("knowledge_graph_nodes")
            .select("*")
            .eq("chatbot_id", chatbot_id)
            .execute()
        )
        edges_result = (
            supabase.table("knowledge_graph_edges")
            .select("*")
            .eq("chatbot_id", chatbot_id)
            .execute()
        )
        return {
            "nodes": nodes_result.data or [],
            "edges": edges_result.data or []
        }
    except Exception as e:
        logging.error(f"Failed to fetch graph data for chatbot {chatbot_id}: {e}")
        return {"nodes": [], "edges": []}

def delete_graph_by_file_id(chatbot_id: int, file_id: int):
    try:
        edges_result = (
            supabase.table("knowledge_graph_edges")
            .delete()
            .eq("chatbot_id", chatbot_id)
            .eq("file_id", file_id)
            .execute()
        )
        nodes_result = (
            supabase.table("knowledge_graph_nodes")
            .delete()
            .eq("chatbot_id", chatbot_id)
            .eq("file_id", file_id)
            .execute()
        )
        return {
            "deleted_nodes_count": len(nodes_result.data or []),
            "deleted_edges_count": len(edges_result.data or [])
        }
    except Exception as e:
        logging.error(f"Failed to delete graph data for file_id {file_id}: {e}")
        return {"deleted_nodes_count": 0, "deleted_edges_count": 0}

def delete_node(chatbot_id: int, name: str):
    try:
        result = (
            supabase.table("knowledge_graph_nodes")
            .delete()
            .eq("chatbot_id", chatbot_id)
            .eq("name", name.strip().lower())
            .execute()
        )
        return result.data if result.data else []
    except Exception as e:
        logging.error(f"Failed to delete node {name} for chatbot {chatbot_id}: {e}")
        return []

def delete_edges_by_node(chatbot_id: int, node_name: str):
    try:
        normalized = node_name.strip().lower()
        res1 = (
            supabase.table("knowledge_graph_edges")
            .delete()
            .eq("chatbot_id", chatbot_id)
            .eq("source_name", normalized)
            .execute()
        )
        res2 = (
            supabase.table("knowledge_graph_edges")
            .delete()
            .eq("chatbot_id", chatbot_id)
            .eq("target_name", normalized)
            .execute()
        )
        return (res1.data or []) + (res2.data or [])
    except Exception as e:
        logging.error(f"Failed to delete edges for node {node_name}: {e}")
        return []

def delete_edge(chatbot_id: int, source_name: str, target_name: str, rel_type: str):
    try:
        result = (
            supabase.table("knowledge_graph_edges")
            .delete()
            .eq("chatbot_id", chatbot_id)
            .eq("source_name", source_name.strip().lower())
            .eq("target_name", target_name.strip().lower())
            .eq("rel_type", rel_type.strip().upper().replace(" ", "_"))
            .execute()
        )
        return result.data if result.data else []
    except Exception as e:
        logging.error(f"Failed to delete edge {source_name} -> {target_name} ({rel_type}): {e}")
        return []

def update_edge_node_references(chatbot_id: int, old_name: str, new_name: str):
    try:
        old_normalized = old_name.strip().lower()
        new_normalized = new_name.strip().lower()
        res1 = (
            supabase.table("knowledge_graph_edges")
            .update({"source_name": new_normalized})
            .eq("chatbot_id", chatbot_id)
            .eq("source_name", old_normalized)
            .execute()
        )
        res2 = (
            supabase.table("knowledge_graph_edges")
            .update({"target_name": new_normalized})
            .eq("chatbot_id", chatbot_id)
            .eq("target_name", old_normalized)
            .execute()
        )
        return (res1.data or []) + (res2.data or [])
    except Exception as e:
        logging.error(f"Failed to update edge references from {old_name} to {new_name}: {e}")
        return []
