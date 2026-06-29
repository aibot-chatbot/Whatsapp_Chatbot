from flask import Blueprint, jsonify, request, g
from app.decorators.auth_decorator import token_required
from app.utils.access_control import verify_chatbot_access, role_required
from app.services.billing_guard import can_upload_knowledge_file, can_use_plan_feature, BillingLimitError
import logging

from app.services.knowledge_service import (
    list_uploaded_pdfs,
    delete_pdf_file,
    get_active_pdf,
    set_active_pdf,
    toggle_supporting_knowledge,
    scrape_website_url,
    discover_website_links,
    scrape_website_urls_batch,
    extract_business_knowledge,
    save_refined_knowledge_chunks,
)

knowledge_blueprint = Blueprint("knowledge", __name__)

@knowledge_blueprint.route("/api/knowledge/files", methods=["GET"])
@token_required
@role_required("admin", "owner")
def get_uploaded_pdfs():
    try:
        chatbot_id = request.args.get("chatbot_id", type=int)
        if not chatbot_id:
            return jsonify({
                "status": "error",
                "message": "chatbot_id is required"
            }), 400

        verify_chatbot_access(chatbot_id)
        files = list_uploaded_pdfs(chatbot_id)
        return jsonify({
            "status": "success",
            "data": files
        }), 200
    except Exception as e:
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500

@knowledge_blueprint.route("/api/knowledge/active", methods=["GET"])
@token_required
@role_required("admin", "owner")
def get_current_active_pdf():
    try:
        chatbot_id = request.args.get("chatbot_id", type=int)
        if not chatbot_id:
            return jsonify({
                "status": "error",
                "message": "chatbot_id is required"
            }), 400

        verify_chatbot_access(chatbot_id)
        active_pdf = get_active_pdf(chatbot_id)
        return jsonify({
            "status": "success",
            "data": active_pdf
        }), 200
    except Exception as e:
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500


@knowledge_blueprint.route("/api/knowledge/set-active", methods=["POST"])
@token_required
@role_required("admin", "owner")
def set_current_active_pdf():
    try:
        data = request.get_json()

        if not data or "file_name" not in data:
            return jsonify({
                "status": "error",
                "message": "file_name is required"
            }), 400

        chatbot_id = request.args.get("chatbot_id", type=int)
        if not chatbot_id:
            return jsonify({
                "status": "error",
                "message": "chatbot_id is required"
            }), 400

        verify_chatbot_access(chatbot_id)
        result = set_active_pdf(data["file_name"], chatbot_id)

        return jsonify({
            "status": "success",
            "data": result
        }), 200

    except ValueError as e:
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 400
    except PermissionError as e:
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 403
    except Exception as e:
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500


@knowledge_blueprint.route("/api/knowledge/toggle-support", methods=["POST"])
@token_required
@role_required("admin", "owner")
def toggle_supporting_knowledge_source():
    try:
        data = request.get_json() or {}

        if "file_name" not in data:
            return jsonify({
                "status": "error",
                "message": "file_name is required"
            }), 400

        if "is_enabled" not in data:
            return jsonify({
                "status": "error",
                "message": "is_enabled is required"
            }), 400

        chatbot_id = request.args.get("chatbot_id", type=int)
        if not chatbot_id:
            return jsonify({
                "status": "error",
                "message": "chatbot_id is required"
            }), 400

        verify_chatbot_access(chatbot_id)
        result = toggle_supporting_knowledge(
            file_name=data["file_name"],
            is_enabled=data["is_enabled"],
            chatbot_id=chatbot_id,
        )

        return jsonify({
            "status": "success",
            "data": result
        }), 200

    except ValueError as e:
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 400
    except PermissionError as e:
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 403
    except Exception as e:
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500


@knowledge_blueprint.route("/api/knowledge/files/<path:file_name>", methods=["DELETE"])
@token_required
@role_required("admin", "owner")
def delete_uploaded_pdf(file_name):
    try:
        chatbot_id = request.args.get("chatbot_id", type=int)
        if not chatbot_id:
            return jsonify({
                "status": "error",
                "message": "chatbot_id is required"
            }), 400

        verify_chatbot_access(chatbot_id)
        
        # Normalize double slashes if Werkzeug collapsed them
        if file_name.startswith("http:/") and not file_name.startswith("http://"):
            file_name = file_name.replace("http:/", "http://", 1)
        elif file_name.startswith("https:/") and not file_name.startswith("https://"):
            file_name = file_name.replace("https:/", "https://", 1)
            
        result = delete_pdf_file(file_name, chatbot_id)
        return jsonify({
            "status": "success",
            "data": result
        }), 200
    except ValueError as e:
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 400
    except Exception as e:
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500


@knowledge_blueprint.route("/api/knowledge/scrape", methods=["POST"])
@token_required
@role_required("admin", "owner")
def scrape_website_knowledge():
    try:
        data = request.get_json()
        if not data or "url" not in data:
            return jsonify({
                "status": "error",
                "message": "URL is required"
            }), 400

        chatbot_id = request.args.get("chatbot_id", type=int)
        if not chatbot_id:
            return jsonify({
                "status": "error",
                "message": "chatbot_id is required"
            }), 400

        verify_chatbot_access(chatbot_id)
        # Check subscription limit before knowledge file creation
        can_upload_knowledge_file(g.company_id)
        result = scrape_website_url(data["url"], chatbot_id)
        return jsonify({
            "status": "success",
            "data": result
        }), 200
    except ValueError as e:
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 400
    except BillingLimitError as e:
        return jsonify({
            "status": "error",
            "code": e.code,
            "message": str(e)
        }), 403

    except Exception as e:
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500


@knowledge_blueprint.route("/api/knowledge/scrape-analyze", methods=["POST"])
@token_required
@role_required("admin", "owner")
def scrape_analyze_website():
    try:
        data = request.get_json()
        if not data or "url" not in data:
            return jsonify({
                "status": "error",
                "message": "URL is required"
            }), 400

        chatbot_id = request.args.get("chatbot_id", type=int)
        if not chatbot_id:
            return jsonify({
                "status": "error",
                "message": "chatbot_id is required"
            }), 400

        verify_chatbot_access(chatbot_id)
        links = discover_website_links(data["url"])
        return jsonify({
            "status": "success",
            "data": {
                "url": data["url"],
                "links": links
            }
        }), 200
    except ValueError as e:
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 400
    except Exception as e:
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500


@knowledge_blueprint.route("/api/knowledge/scrape-batch", methods=["POST"])
@token_required
@role_required("admin", "owner")
def scrape_batch_website():
    try:
        data = request.get_json()
        if not data or "urls" not in data or not isinstance(data["urls"], list):
            return jsonify({
                "status": "error",
                "message": "List of URLs ('urls') is required"
            }), 400

        chatbot_id = request.args.get("chatbot_id", type=int)
        if not chatbot_id:
            return jsonify({
                "status": "error",
                "message": "chatbot_id is required"
            }), 400

        verify_chatbot_access(chatbot_id)
        # Check subscription feature access for batch scraping
        can_use_plan_feature(g.company_id, "batch_website_scraping")
        # Check subscription limit before knowledge file creation
        can_upload_knowledge_file(g.company_id)
        result = scrape_website_urls_batch(data["urls"], chatbot_id)
        return jsonify({
            "status": "success",
            "data": result
        }), 200
    except ValueError as e:
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 400
    except BillingLimitError as e:
        return jsonify({
            "status": "error",
            "code": e.code,
            "message": str(e)
        }), 403

    except Exception as e:
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500


@knowledge_blueprint.route("/api/knowledge/scrape-extract", methods=["POST"])
@token_required
@role_required("admin", "owner")
def scrape_extract_website():
    try:
        from app.services.knowledge_service import fetch_and_parse_url
        data = request.get_json()
        if not data or "urls" not in data or not isinstance(data["urls"], list):
            return jsonify({
                "status": "error",
                "message": "List of URLs ('urls') is required"
            }), 400

        chatbot_id = request.args.get("chatbot_id", type=int)
        if not chatbot_id:
            return jsonify({
                "status": "error",
                "message": "chatbot_id is required"
            }), 400

        verify_chatbot_access(chatbot_id)
        # Check subscription feature access for batch website scraping
        can_use_plan_feature(g.company_id, "batch_website_scraping")

        urls = data["urls"]
        if not urls:
            return jsonify({
                "status": "error",
                "message": "At least one URL must be selected."
            }), 400

        combined_content_list = []
        failed_urls = []
        primary_url = urls[0]

        for url in urls:
            try:
                content = fetch_and_parse_url(url)
                combined_content_list.append(content)
            except Exception as e:
                import logging
                logging.error(f"Failed to scrape URL {url} for extraction: {e}")
                failed_urls.append(url)

        if not combined_content_list:
            return jsonify({
                "status": "error",
                "message": f"Failed to scrape any of the selected URLs. Errors: {failed_urls}"
            }), 400

        combined_text = "\n\n".join(combined_content_list)
        
        # Call the LLM refiner
        refined_text = extract_business_knowledge(combined_text, chatbot_id=chatbot_id)

        return jsonify({
            "status": "success",
            "data": {
                "extracted_text": refined_text,
                "primary_url": primary_url,
                "failed_urls": failed_urls
            }
        }), 200
    except BillingLimitError as e:
        return jsonify({
            "status": "error",
            "code": e.code,
            "message": str(e),
            "details": e.details or {}
        }), 403
    except Exception as e:
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500


@knowledge_blueprint.route("/api/knowledge/scrape-embed", methods=["POST"])
@token_required
@role_required("admin", "owner")
def scrape_embed_website():
    try:
        data = request.get_json()
        if not data or "text_content" not in data or "primary_url" not in data:
            return jsonify({
                "status": "error",
                "message": "text_content and primary_url are required"
            }), 400

        chatbot_id = request.args.get("chatbot_id", type=int)
        if not chatbot_id:
            return jsonify({
                "status": "error",
                "message": "chatbot_id is required"
            }), 400

        verify_chatbot_access(chatbot_id)

        # Check subscription limit before knowledge file creation
        can_upload_knowledge_file(g.company_id)

        text_content = data["text_content"]
        primary_url = data["primary_url"]
        
        # Default file name is the primary URL or custom override
        file_name = data.get("file_name", primary_url)

        result = save_refined_knowledge_chunks(
            text_content=text_content,
            file_name=file_name,
            primary_url=primary_url,
            chatbot_id=chatbot_id
        )

        return jsonify({
            "status": "success",
            "data": result
        }), 200
    except ValueError as e:
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 400
    except BillingLimitError as e:
        return jsonify({
            "status": "error",
            "code": e.code,
            "message": str(e)
        }), 403

    except Exception as e:
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500



@knowledge_blueprint.route("/api/knowledge/graph", methods=["GET"])
@token_required
@role_required("admin", "owner")
def get_knowledge_graph_data():
    try:
        chatbot_id = request.args.get("chatbot_id", type=int)
        if not chatbot_id:
            return jsonify({
                "status": "error",
                "message": "chatbot_id is required"
            }), 400

        verify_chatbot_access(chatbot_id)
        
        from app.database.db import supabase
        from app.database.knowledge_file_repository import get_active_pdf_knowledge_file
        from app.database.knowledge_chunk_repository import get_chunks_by_file_for_chatbot
        from app.services.knowledge_service import extract_and_store_graph_supabase
        
        # 1. Identify the current active PDF knowledge file
        active_file = get_active_pdf_knowledge_file(chatbot_id)
        if not active_file:
            return jsonify({
                "status": "success",
                "data": {
                    "nodes": [],
                    "edges": []
                }
            }), 200
            
        file_id = active_file["id"]
        
        # 2. Check if we have nodes for this active PDF
        nodes_check = (
            supabase.table("knowledge_graph_nodes")
            .select("id")
            .eq("chatbot_id", chatbot_id)
            .eq("file_id", file_id)
            .limit(1)
            .execute()
        )
        
        # 3. If no nodes exist, auto-trigger extraction synchronously
        if not nodes_check.data:
            logging.info(f"[GraphRAG] No nodes found for active file_id={file_id}. Running auto-extraction...")
            chunks_data = get_chunks_by_file_for_chatbot(chatbot_id, file_id)
            chunks = [c["content"] for c in chunks_data]
            
            # Self-healing: if 0 chunks exist, attempt to parse the local PDF file from the disk
            if not chunks:
                logging.info(f"[GraphRAG] Chunks count is 0 in DB. Attempting to parse physical PDF file...")
                from app.services.knowledge_service import DATA_FOLDER
                import os
                import fitz
                from app.services.rag_service import split_text_into_sections, generate_embedding
                from app.database.knowledge_chunk_repository import save_knowledge_chunk
                
                file_name = active_file.get("file_name", "")
                stored_path = active_file.get("file_path", "")
                from werkzeug.utils import secure_filename
                
                # Robust path candidates lookup
                candidates = []
                if stored_path:
                    if os.path.isabs(stored_path):
                        candidates.append(stored_path)
                    else:
                        candidates.append(os.path.join(DATA_FOLDER, os.path.basename(stored_path)))
                        
                candidates.extend([
                    os.path.join(DATA_FOLDER, file_name),
                    os.path.join(DATA_FOLDER, f"bot_{chatbot_id}_{file_name}"),
                    os.path.join(DATA_FOLDER, secure_filename(file_name)),
                    os.path.join(DATA_FOLDER, secure_filename(f"bot_{chatbot_id}_{file_name}")),
                ])
                
                target_path = None
                for path in candidates:
                    if path and os.path.exists(path):
                        target_path = path
                        break
                        
                logging.info(f"[GraphRAG] Resolved path candidates: {candidates} -> Chosen: {target_path}")
                    
                if target_path:
                    try:
                        doc = fitz.open(target_path)
                        lines = []
                        for page in doc:
                            blocks = page.get_text("blocks")
                            blocks = sorted(blocks, key=lambda b: (b[1], b[0]))
                            for block in blocks:
                                text = block[4].strip()
                                if text:
                                    for line in text.splitlines():
                                        clean_line = " ".join(line.split())
                                        if clean_line:
                                            lines.append(clean_line)
                        pdf_text = "\n".join(lines)
                        chunks = split_text_into_sections(pdf_text)
                        
                        logging.info(f"[GraphRAG] Extracted {len(chunks)} chunks from local PDF. Saving to database...")
                        for idx, chunk in enumerate(chunks):
                            embedding = generate_embedding(chunk)
                            if embedding:
                                save_knowledge_chunk(
                                    chatbot_id=chatbot_id,
                                    file_id=file_id,
                                    content=chunk,
                                    embedding=embedding,
                                    metadata={"chunk_index": idx}
                                )
                    except Exception as parse_err:
                        logging.error(f"[GraphRAG] Failed to parse local PDF file {target_path}: {parse_err}")
                else:
                    logging.error(f"[GraphRAG] Local PDF file does not exist for candidates: {candidates}")
            
            if chunks:
                try:
                    extract_and_store_graph_supabase(chunks, chatbot_id, file_id)
                except Exception as ext_err:
                    logging.error(f"[GraphRAG] Auto-extraction failed for file_id={file_id}: {ext_err}")
        
        # 4. Fetch graph elements ONLY for this active PDF file
        nodes_result = (
            supabase.table("knowledge_graph_nodes")
            .select("*")
            .eq("chatbot_id", chatbot_id)
            .eq("file_id", file_id)
            .execute()
        )
        
        edges_result = (
            supabase.table("knowledge_graph_edges")
            .select("*")
            .eq("chatbot_id", chatbot_id)
            .eq("file_id", file_id)
            .execute()
        )
        
        # Format nodes and edges for frontend graphing libraries (like vis.js)
        formatted_nodes = []
        for node in (nodes_result.data or []):
            formatted_nodes.append({
                "id": node["name"],
                "label": node["name"].title(),
                "title": f"Type: {node['label']}\n{node.get('properties', {}).get('description', '')}".strip(),
                "group": node["label"]
            })
            
        formatted_edges = []
        for edge in (edges_result.data or []):
            formatted_edges.append({
                "from": edge["source_name"],
                "to": edge["target_name"],
                "label": edge["rel_type"].replace("_", " "),
                "title": edge["rel_type"]
            })
            
        return jsonify({
            "status": "success",
            "data": {
                "nodes": formatted_nodes,
                "edges": formatted_edges
            }
        }), 200
    except Exception as e:
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500
 
 
@knowledge_blueprint.route("/api/knowledge/refinement/questions", methods=["GET"])
@token_required
@role_required("admin", "owner")
def get_refinement_questions():
    try:
        chatbot_id = request.args.get("chatbot_id", type=int)
        if not chatbot_id:
            return jsonify({
                "status": "error",
                "message": "chatbot_id is required"
            }), 400

        verify_chatbot_access(chatbot_id)
        
        from app.database.db import supabase
        from app.database.knowledge_file_repository import get_active_pdf_knowledge_file
        
        # 1. Get active PDF
        active_file = get_active_pdf_knowledge_file(chatbot_id)
        if not active_file:
            return jsonify({
                "status": "error",
                "message": "No active primary PDF found. Please set a primary PDF before scanning for clarifications."
            }), 400
            
        file_id = active_file["id"]
        
        # 2. Get graph elements for this PDF
        nodes_res = (
            supabase.table("knowledge_graph_nodes")
            .select("*")
            .eq("chatbot_id", chatbot_id)
            .eq("file_id", file_id)
            .execute()
        )
        
        edges_res = (
            supabase.table("knowledge_graph_edges")
            .select("*")
            .eq("chatbot_id", chatbot_id)
            .eq("file_id", file_id)
            .execute()
        )
        
        nodes = nodes_res.data or []
        edges = edges_res.data or []
        
        if not nodes:
            return jsonify({
                "status": "error",
                "message": "No knowledge graph elements found for this PDF. The graph must be populated first."
            }), 400
            
        # 3. Format the graph elements into a summary prompt
        graph_text = f"Here is the knowledge graph extracted from active file '{active_file['file_name']}':\n\n"
        graph_text += "Entities (Nodes):\n"
        for n in nodes:
            graph_text += f"- {n['name']} (Category: {n['label']})"
            if n.get("properties") and isinstance(n["properties"], dict):
                props_str = ", ".join(f"{k}: {v}" for k, v in n["properties"].items())
                if props_str:
                    graph_text += f" | Details: {props_str}"
            graph_text += "\n"
            
        graph_text += "\nConnections (Edges):\n"
        for e in edges:
            graph_text += f"- {e['source_name']} [{e['rel_type']}] -> {e['target_name']}\n"
            
        # 4. Prompt LLM to analyze graph gaps
        system_prompt = (
            "You are a knowledge graph refinement assistant for a customer support AI chatbot.\n"
            "Your task is to analyze the extracted business knowledge graph and identify 3 to 5 critical clarifying questions "
            "that a customer might ask but are ambiguous, incomplete, or lack specific details in the current nodes/relationships "
            "(e.g., missing prices, undefined warranties, service limitations, shipping times, or package details).\n"
            "You must return the result as a raw JSON array of objects with the fields: 'question' and 'context'.\n"
            "Example output format:\n"
            "[\n"
            "  {\"question\": \"What is the warranty period for Titan Laptop?\", \"context\": \"Titan Laptop is connected to Warranty, but details/duration are not specified.\"},\n"
            "  {\"question\": \"How much does the Platinum Package cost?\", \"context\": \"Platinum Package is a Service, but has no HAS_PRICE relation.\"}\n"
            "]\n"
            "Return ONLY the raw JSON block without markdown formatting."
        )
        
        import os
        from openai import OpenAI
        api_key = os.getenv("DEEPSEEK_API_KEY")
        if not api_key:
            api_key = os.getenv("OPENROUTER_API_KEY")
            client = OpenAI(
                api_key=api_key,
                base_url="https://openrouter.ai/api/v1"
            )
            model = "deepseek/deepseek-chat"
        else:
            client = OpenAI(
                api_key=api_key,
                base_url="https://api.deepseek.com"
            )
            model = "deepseek-chat"
            
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": graph_text}
            ],
            temperature=0.3
        )
        
        content = response.choices[0].message.content.strip()
        if content.startswith("```"):
            lines = content.splitlines()
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines[-1].startswith("```"):
                lines = lines[:-1]
            content = "\n".join(lines).strip()
            
        import json
        questions = json.loads(content)
        
        return jsonify({
            "status": "success",
            "data": questions
        }), 200
        
    except Exception as e:
        logging.error(f"[Refinement] Failed to generate questions: {e}")
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500


@knowledge_blueprint.route("/api/knowledge/refinement/submit", methods=["POST"])
@token_required
@role_required("admin", "owner")
def submit_refinement_answers():
    try:
        chatbot_id = request.args.get("chatbot_id", type=int)
        if not chatbot_id:
            return jsonify({
                "status": "error",
                "message": "chatbot_id is required"
            }), 400

        verify_chatbot_access(chatbot_id)
        
        data = request.get_json()
        answers = data.get("answers", [])
        if not answers:
            return jsonify({
                "status": "error",
                "message": "No answers provided"
            }), 400
            
        from app.database.knowledge_file_repository import get_active_pdf_knowledge_file
        from app.services.rag_service import generate_embedding
        from app.database.knowledge_chunk_repository import save_knowledge_chunk
        
        # 1. Get active PDF
        active_file = get_active_pdf_knowledge_file(chatbot_id)
        if not active_file:
            return jsonify({
                "status": "error",
                "message": "No active primary PDF found."
            }), 400
            
        file_id = active_file["id"]
        
        # 2. Save each answer as a new chunk with embeddings
        saved_count = 0
        for item in answers:
            question = item.get("question", "").strip()
            answer = item.get("answer", "").strip()
            if not question or not answer:
                continue
                
            chunk_content = f"Question: {question}\nAnswer: {answer}"
            embedding = generate_embedding(chunk_content)
            if embedding:
                save_knowledge_chunk(
                    chatbot_id=chatbot_id,
                    file_id=file_id,
                    content=chunk_content,
                    embedding=embedding,
                    metadata={
                        "source_type": "refinement",
                        "question": question,
                        "refined_at": "2026-06-29"
                    }
                )
                saved_count += 1
                
        return jsonify({
            "status": "success",
            "message": f"Successfully saved {saved_count} refined knowledge clarifications."
        }), 200
        
    except Exception as e:
        logging.error(f"[Refinement] Failed to submit answers: {e}")
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500
