"""Ask endpoint: POST /ask - main Q&A endpoint."""

import json
import logging
import os
import time
import traceback
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from auth import verify_token
from database import get_db, User, Agent, Document, DocumentChunk, Conversation, Message, AgentAction, Team
from helpers.agent_helpers import resolve_model_id, _user_can_access_agent
from helpers.rate_limiting import _check_api_rate_limit, _API_ASK_LIMIT
from helpers.tenant import _get_caller_company_id
from mistral_embeddings import get_embedding
from rag_engine import get_answer, get_answer_with_files, get_answer_stream
from redis_client import get_cached_user
from utils import logger as app_logger, event_tracker
from utils_ai import normalize_model_output, extract_json_object_from_text
from validation import QuestionRequestValidated

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/ask")
async def ask_question(
    request: QuestionRequestValidated, user_id: str = Depends(verify_token), db: Session = Depends(get_db)
):
    """Ask question to RAG system (toujours avec mémoire et bon modèle)"""
    if not _check_api_rate_limit(user_id, "ask", _API_ASK_LIMIT):
        raise HTTPException(status_code=429, detail="Too many requests. Please try again later.")
    start_time = time.time()
    try:
        logger.info(f"Processing question from user {user_id}: {request.question}")
        logger.info(f"Selected documents: {request.selected_documents}")

        # Récupérer l'historique complet de la conversation si conversation_id fourni
        history = []
        if hasattr(request, "conversation_id") and request.conversation_id:
            msgs = (
                db.query(Message)
                .filter(Message.conversation_id == request.conversation_id)
                .order_by(Message.timestamp.asc())
                .all()
            )
            history = [{"role": m.role, "content": m.content} for m in msgs]
        elif hasattr(request, "history") and request.history:
            # fallback: si le frontend envoie déjà l'historique
            history = request.history

        answer = None
        agent = None
        model_id = None
        # Si agent_id fourni, comportement agent classique
        if request.agent_id:
            from database import Agent

            agent = _user_can_access_agent(int(user_id), request.agent_id, db)
            model_id = agent.finetuned_model_id or resolve_model_id(agent)
            logger.info(
                f"[LLM ROUTING] Agent '{agent.name}' type={getattr(agent, 'type', 'unknown')} -> model_id={model_id}"
            )
            question_finale = request.question
            prompt = f"Sachant le contexte et la discussion en cours, réponds à cette question : {question_finale}"
            answer = get_answer(
                prompt,
                int(user_id),
                db,
                selected_doc_ids=request.selected_documents,
                agent_id=request.agent_id,
                history=history,
                model_id=model_id,
                company_id=agent.company_id,
            )
        # Si team_id fourni, on va chercher le chef d'équipe et les sous-agents
        elif request.team_id:
            from database import Team, Agent
            import numpy as np

            team = db.query(Team).filter(Team.id == request.team_id).first()
            if not team:
                raise HTTPException(status_code=404, detail="Team not found")
            if team.user_id != int(user_id):
                raise HTTPException(status_code=403, detail="Access denied to this team")
            leader = db.query(Agent).filter(Agent.id == team.leader_agent_id).first()
            if not leader:
                raise HTTPException(status_code=404, detail="Leader agent not found")

            # Récupérer TOUS les sous-agents (actionnables ET conversationnels)
            all_sub_agent_ids = []
            if team.action_agent_ids:
                try:
                    action_ids = (
                        json.loads(team.action_agent_ids)
                        if isinstance(team.action_agent_ids, str)
                        else team.action_agent_ids
                    )
                    all_sub_agent_ids.extend(action_ids)
                except:
                    pass

            # Récupérer les sous-agents depuis la base
            sub_agents = []
            if all_sub_agent_ids:
                sub_agents = db.query(Agent).filter(Agent.id.in_(all_sub_agent_ids)).all()

            best_agent = None
            best_score = -1

            # Si on a des sous-agents avec embeddings, faire le matching sémantique
            if sub_agents:
                try:
                    prompt_embedding = get_embedding(request.question)
                    for a in sub_agents:
                        if not a.embedding:
                            continue
                        try:
                            emb = np.array(json.loads(a.embedding))
                            score = float(
                                np.dot(prompt_embedding, emb) / (np.linalg.norm(prompt_embedding) * np.linalg.norm(emb))
                            )
                            if score > best_score:
                                best_score = score
                                best_agent = a
                        except Exception:
                            continue
                except Exception as e:
                    logger.warning(f"Error during semantic matching: {e}")

            # Si aucun sous-agent qualifié, utiliser le leader directement
            if not best_agent:
                logger.info(f"No sub-agent matched, using leader agent {leader.name}")
                best_agent = leader

            # Appel get_answer avec l'agent sélectionné
            if best_agent.finetuned_model_id:
                model_id = best_agent.finetuned_model_id
            else:
                atype = getattr(best_agent, "type", "conversationnel")
                if atype == "recherche_live":
                    model_id = os.getenv("PERPLEXITY_MODEL", "perplexity:sonar")
                else:
                    model_id = os.getenv("MISTRAL_MODEL", "mistral:mistral-small-latest")
            prompt = f"Sachant le contexte et la discussion en cours, réponds à cette question : {request.question}"
            agent_answer = get_answer(
                prompt,
                int(user_id),
                db,
                selected_doc_ids=request.selected_documents,
                agent_id=best_agent.id,
                history=history,
                model_id=model_id,
                company_id=best_agent.company_id,
            )

            # Réponse formatée
            if best_agent.id == leader.id:
                answer = agent_answer
            else:
                answer = f"Pour répondre à votre question, j'ai fait appel à l'agent {best_agent.name}. Voici sa réponse :\n{agent_answer}"
            agent = best_agent

        if answer is None:
            raise HTTPException(status_code=400, detail="Aucun agent ou équipe valide fourni.")

        response_time = time.time() - start_time
        logger.info(f"Question answered for user {user_id} in {response_time:.2f}s")
        event_tracker.track_question_asked(int(user_id), request.question, response_time)
        return {"answer": answer}
    except Exception as e:
        logger.error(f"Error answering question for user {user_id}: {e}")
        return {"answer": "Désolé, une erreur s'est produite lors du traitement de votre question. Veuillez réessayer."}


@router.post("/ask-stream")
async def ask_question_stream(
    request: QuestionRequestValidated, user_id: str = Depends(verify_token), db: Session = Depends(get_db)
):
    """Streaming version of /ask. Returns Server-Sent Events with token-by-token response."""
    from streaming_response import sse_event

    if not _check_api_rate_limit(user_id, "ask", _API_ASK_LIMIT):
        raise HTTPException(status_code=429, detail="Too many requests. Please try again later.")

    # Retrieve conversation history
    history = []
    if hasattr(request, "conversation_id") and request.conversation_id:
        msgs = (
            db.query(Message)
            .filter(Message.conversation_id == request.conversation_id)
            .order_by(Message.timestamp.asc())
            .all()
        )
        history = [{"role": m.role, "content": m.content} for m in msgs]
    elif hasattr(request, "history") and request.history:
        history = request.history

    def event_generator():
        try:
            agent = None
            model_id = None

            if request.agent_id:
                agent = _user_can_access_agent(int(user_id), request.agent_id, db)
                model_id = agent.finetuned_model_id or resolve_model_id(agent)
                question_finale = request.question
                prompt = f"Sachant le contexte et la discussion en cours, réponds à cette question : {question_finale}"
                yield from get_answer_stream(
                    prompt,
                    int(user_id),
                    db,
                    selected_doc_ids=request.selected_documents,
                    agent_id=request.agent_id,
                    history=history,
                    model_id=model_id,
                    company_id=agent.company_id,
                )
            elif request.team_id:
                import numpy as np

                team = db.query(Team).filter(Team.id == request.team_id).first()
                if not team:
                    yield sse_event("error", {"message": "Team not found", "code": "not_found"})
                    return
                if team.user_id != int(user_id):
                    yield sse_event("error", {"message": "Access denied", "code": "forbidden"})
                    return
                leader = db.query(Agent).filter(Agent.id == team.leader_agent_id).first()
                if not leader:
                    yield sse_event("error", {"message": "Leader agent not found", "code": "not_found"})
                    return

                all_sub_agent_ids = []
                if team.action_agent_ids:
                    try:
                        action_ids = (
                            json.loads(team.action_agent_ids)
                            if isinstance(team.action_agent_ids, str)
                            else team.action_agent_ids
                        )
                        all_sub_agent_ids.extend(action_ids)
                    except Exception:
                        pass

                sub_agents = []
                if all_sub_agent_ids:
                    sub_agents = db.query(Agent).filter(Agent.id.in_(all_sub_agent_ids)).all()

                best_agent = None
                best_score = -1

                if sub_agents:
                    try:
                        prompt_embedding = get_embedding(request.question)
                        for a in sub_agents:
                            if not a.embedding:
                                continue
                            try:
                                emb = np.array(json.loads(a.embedding))
                                score = float(
                                    np.dot(prompt_embedding, emb)
                                    / (np.linalg.norm(prompt_embedding) * np.linalg.norm(emb))
                                )
                                if score > best_score:
                                    best_score = score
                                    best_agent = a
                            except Exception:
                                continue
                    except Exception as e:
                        logger.warning(f"Error during semantic matching: {e}")

                if not best_agent:
                    best_agent = leader

                if best_agent.finetuned_model_id:
                    model_id = best_agent.finetuned_model_id
                else:
                    atype = getattr(best_agent, "type", "conversationnel")
                    if atype == "recherche_live":
                        model_id = os.getenv("PERPLEXITY_MODEL", "perplexity:sonar")
                    else:
                        model_id = os.getenv("MISTRAL_MODEL", "mistral:mistral-small-latest")

                prompt = f"Sachant le contexte et la discussion en cours, réponds à cette question : {request.question}"

                # If using a sub-agent, prepend routing info
                if best_agent.id != leader.id:
                    prefix = f"Pour répondre à votre question, j'ai fait appel à l'agent {best_agent.name}. Voici sa réponse :\n"
                    yield sse_event("token", {"t": prefix})

                yield from get_answer_stream(
                    prompt,
                    int(user_id),
                    db,
                    selected_doc_ids=request.selected_documents,
                    agent_id=best_agent.id,
                    history=history,
                    model_id=model_id,
                    company_id=best_agent.company_id,
                )
            else:
                yield sse_event("error", {"message": "Aucun agent ou équipe valide fourni.", "code": "bad_request"})

        except Exception as e:
            logger.error(f"Error in ask-stream: {e}")
            yield sse_event("error", {"message": str(e), "code": "llm_error"})

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


_ACTIONNABLE_REMOVED = """
                    {
                        "name": "create_google_doc",
                        "description": "Create a Google Doc and return its URL",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "title": {"type": "string"},
                                "content": {"type": "string"},
                                "folder_id": {"type": "string"}
                            },
                            "required": ["title"]
                        }
                    },
                    {
                        "name": "create_google_sheet",
                        "description": "Create a Google Sheet and optionally populate structured sheets",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "title": {"type": "string"},
                                "sheets": {
                                    "type": "array",
                                    "items": {
                                        "type": "object",
                                        "properties": {
                                            "title": {"type": "string"},
                                            "headers": {"type": "array", "items": {"type": "string"}},
                                            "rows": {"type": "array", "items": {"type": "array", "items": {"type": ["string","number"]}}},
                                            "formulas": {"type": "array"},
                                            "conditional_formats": {"type": "array"}
                                        },
                                        "required": ["title","headers"]
                                    }
                                },
                                "folder_id": {"type": "string"}
                            },
                            "required": ["title","sheets"]
                        }
                    },
                    {
                        "name": "echo",
                        "description": "Echo back a message",
                        "parameters": {"type": "object", "properties": {"text": {"type": "string"}}}
                    },
                    {
                        "name": "write_local_file",
                        "description": "Write a local debug file on the server",
                        "parameters": {"type": "object", "properties": {"filename": {"type": "string"}, "content": {"type": "string"}}}
                    }
                ]

                # Build messages for the structured call: include a couple of short examples (few-shot)
                struct_messages = []
                # Strong instruction for models (Gemini) used by actionnable agents:
                # If an action is appropriate, respond with ONLY a JSON object in the shape
                # {"name": "<action_name>", "arguments": {...}} and nothing else. If no action
                # is required, reply with normal assistant text.
                struct_messages.append({
                    "role": "system",
                    "content": (
                        "Quand une action doit être exécutée, réponds STRICTEMENT et UNIQUEMENT avec un objet JSON de la forme :\n"
                        "{\n  \"function_call\": {\n    \"name\": \"<nom_de_l_action>\",\n    \"arguments\": { ... }\n  }\n}\n"
                        "N’ajoute aucune explication, texte ou commentaire. Si aucune action n’est requise, réponds avec un texte normal d’assistant."
                    )
                })
                example_user_sheet = (
                    "Exemple: Crée un Google Sheet intitulé \"Tableau RH exemple\" avec une feuille 'Employés'"
                    " contenant les colonnes Nom, Département, Poste, Salaire mensuel et une ligne d'exemple: Alice, IT, Dev, 4000."
                )
                example_assistant_sheet = (
                    '{'
                    '"function_call": {'
                    '"name": "create_google_sheet",'
                    '"arguments": {'
                    '"title":"Tableau RH exemple",'
                    '"sheets":[{"title":"Employés","headers":["Nom","Département","Poste","Salaire mensuel"],'
                    '"rows":[["Alice","IT","Dev",4000]]}]'
                    '}'
                    '}'
                    '}'
                )
                example_user_doc = (
                    "Exemple: Crée un Google Doc intitulé \"Note projet\" qui contient un court résumé et des actions à mener."
                )
                example_assistant_doc = (
                    '{'
                    '"function_call": {'
                    '"name": "create_google_doc",'
                    '"arguments": {'
                    '"title":"Note projet",'
                    '"content":"Résumé: ...\\nActions:\\n- Action 1\\n- Action 2"'
                    '}'
                    '}'
                    '}'
                )

                if agent and getattr(agent, 'contexte', None):
                    struct_messages.append({"role": "system", "content": agent.contexte})
                struct_messages.append({"role": "user", "content": example_user_sheet})
                struct_messages.append({"role": "assistant", "content": example_assistant_sheet})
                struct_messages.append({"role": "user", "content": example_user_doc})
                struct_messages.append({"role": "assistant", "content": example_assistant_doc})

                # For actionnable agents (Gemini), normalize the assistant answer to plain text for the structured call
                try:
                    assistant_context = normalize_model_output(answer)
                except Exception:
                    assistant_context = str(answer)
                struct_messages.append({"role": "assistant", "content": assistant_context})
                struct_messages.append({"role": "user", "content": request.question})

                # Enforce Gemini-only for actionnable agents' structured calls
                struct_gemini_only = True

                # Heuristic: if the user's question strongly indicates a spreadsheet/table request
                # prefer calling create_google_sheet; if it indicates a document, prefer create_google_doc.
                forced_call = None
                try:
                    q = (request.question or "").lower()
                    sheet_keywords = ["table", "tableau", "spreadsheet", "sheet", "tableur", "excel", "csv"]
                    doc_keywords = ["document", "doc", "note", "rapport", "résumé", "resume"]
                    if any(k in q for k in sheet_keywords):
                        forced_call = {"name": "create_google_sheet"}
                    elif any(k in q for k in doc_keywords):
                        forced_call = {"name": "create_google_doc"}
                except Exception:
                    forced_call = None

                message = get_chat_response_structured(struct_messages, functions=functions, function_call=forced_call, model_id=model_id, gemini_only=struct_gemini_only)

                action_results = []
                # If model requested a function call, execute it
                if hasattr(message, 'function_call') and message.function_call:
                    fc = message.function_call
                else:
                    # Fallback: some providers (or Gemini text outputs) return JSON text rather
                    # than a structured function_call attribute. Try to parse message.content
                    # as JSON and extract a function_call-shaped object.
                    fc = None
                    try:
                        raw_text = getattr(message, 'content', None) if hasattr(message, 'content') else str(message)
                        logger.info(f"Structured call: no function_call attribute; raw model output: {raw_text}")
                        # Try a more robust JSON extraction/parsing from the raw text
                        try:
                            parsed = extract_json_object_from_text(raw_text)
                            if parsed is None:
                                logger.debug("No JSON object could be extracted from raw model output")
                            else:
                                logger.debug(f"Parsed JSON object from model output (type={type(parsed).__name__})")
                                if isinstance(parsed, dict):
                                    if 'function_call' in parsed and isinstance(parsed['function_call'], dict):
                                        fc = parsed['function_call']
                                    elif 'name' in parsed and ('arguments' in parsed or 'params' in parsed or 'parameters' in parsed):
                                        fc = {'name': parsed.get('name'), 'arguments': parsed.get('arguments') or parsed.get('params') or parsed.get('parameters')}
                                    elif 'action' in parsed and 'params' in parsed:
                                        fc = {'name': parsed.get('action'), 'arguments': parsed.get('params')}
                                    else:
                                        # If parsed dict looks like arguments only, attempt to infer action name
                                        # by searching for common action names in the raw text.
                                        for candidate in ('create_google_sheet', 'create_google_doc', 'echo', 'write_local_file'):
                                            if candidate in raw_text:
                                                fc = {'name': candidate, 'arguments': parsed}
                                                break
                        except Exception as e:
                            logger.debug(f"Could not parse raw model output as JSON function_call fallback: {e}")
                    except Exception as e:
                        logger.debug(f"Could not parse raw model output as JSON function_call fallback: {e}")
                    try:
                        if isinstance(fc, dict):
                            name = fc.get('name')
                            arguments = fc.get('arguments')
                        else:
                            name = getattr(fc, 'name', None) or getattr(fc, 'function_name', None)
                            arguments = getattr(fc, 'arguments', None) or getattr(fc, 'params', None)
                        payload = {"name": name, "arguments": arguments}
                        logger.info(f"Prepared action payload: {payload}")

                        try:
                            args_obj = payload.get("arguments")
                            if isinstance(args_obj, str):
                                try:
                                    args_parsed = json.loads(args_obj)
                                except Exception:
                                    args_parsed = {"_raw": args_obj}
                            elif isinstance(args_obj, dict):
                                args_parsed = args_obj
                            else:
                                args_parsed = {"_raw": str(args_obj)}

                            if isinstance(args_parsed, dict) and ("_raw" not in args_parsed or not args_parsed.get("_raw")):
                                args_parsed["_raw"] = request.question

                            payload["arguments"] = args_parsed
                        except Exception:
                            pass

                        # If create_google_sheet, attempt validation and one repair pass
                        try:
                            if payload.get("name") == "create_google_sheet":
                                try:
                                    import jsonschema
                                    sheet_schema = {
                                        "type": "object",
                                        "properties": {
                                            "title": {"type": "string"},
                                            "sheets": {"type": "array"},
                                            "folder_id": {"type": "string"}
                                        },
                                        "required": ["title","sheets"]
                                    }
                                    if isinstance(payload.get("arguments"), dict):
                                        jsonschema.validate(payload.get("arguments"), sheet_schema)
                                    else:
                                        raise jsonschema.ValidationError("Arguments not an object")
                                except Exception:
                                    try:
                                        from openai_client import get_chat_response_json
                                        repair_msgs = [
                                            {"role": "system", "content": "You must return ONLY a JSON object that matches the requested schema for the function arguments. No explanation."},
                                            {"role": "user", "content": f"The user asked: {request.question}\nPlease return the function arguments JSON that matches this schema: {json.dumps(sheet_schema, ensure_ascii=False)}"}
                                        ]
                                        corrected = get_chat_response_json(repair_msgs, schema=sheet_schema, model_id=model_id, gemini_only=True)
                                        if isinstance(corrected, dict):
                                            payload["arguments"] = corrected
                                    except Exception:
                                        pass
                        except Exception:
                            pass
                    except Exception:
                        payload = {"name": None, "arguments": None}

                    if payload.get("name"):
                        result = parse_and_execute_actions(payload, db=db, agent_id=request.agent_id, user_id=int(user_id), company_id=_get_caller_company_id(user_id, db))
                        action_results.append({"action": payload.get("name"), "result": result})
                    else:
                        action_results.append({"status": "error", "error": "Could not parse function_call from model response"})

                # If any action succeeded, ask the model to generate a short assistant confirmation
                try:
                    confirmations = []
                    for ar in action_results:
                        res = ar.get("result") if isinstance(ar, dict) else None
                        if isinstance(res, dict) and res.get("status") == "ok":
                            payload_result = res.get("result") if isinstance(res.get("result"), dict) else None
                            if payload_result:
                                url = payload_result.get("url") or payload_result.get("webViewLink")
                                if url:
                                    confirmations.append(url)
                                    continue
                                doc_id = payload_result.get("document_id") or payload_result.get("spreadsheetId")
                                if doc_id:
                                    confirmations.append(str(doc_id))
                                    continue
                                path = payload_result.get("path")
                                if path:
                                    confirmations.append(path)

                    if confirmations:
                        messages_for_model = []
                        if agent and getattr(agent, 'contexte', None):
                            messages_for_model.append({"role": "system", "content": agent.contexte})
                        messages_for_model.append({"role": "assistant", "content": answer})
                        links_text = "\n".join([f"- {u}" for u in confirmations])
                        user_instruction = (
                            f'Suite à ce prompt "{request.question}" les actions suivantes ont été exécutées :\n'
                            + links_text + "\n\n"
                            + "Génère une réponse d'assistant courte et affirmative en français confirmant que l'action a été réalisée."
                        )
                        messages_for_model.append({"role": "user", "content": user_instruction})
                        try:
                            crafted = get_chat_response(messages_for_model, model_id=model_id, gemini_only=True)
                            # Normalize and strip markdown-style links so the frontend shows full URLs
                            try:
                                raw_crafted = normalize_model_output(crafted)
                            except Exception:
                                raw_crafted = str(crafted)
                            try:
                                                        # Replace markdown links [text](url) with the raw url
                                raw_crafted = re.sub(r"\[([^\]]+)\]\((https?://[^)]+)\)", r"\2", raw_crafted)
                                # Also replace simple HTML anchors <a href="url">text</a>
                                raw_crafted = re.sub(r"<a\s+[^>]*href=[\"'](https?://[^\"']+)[\"'][^>]*>.*?<\/a>", r"\1", raw_crafted, flags=re.IGNORECASE)
                            except Exception:
                                pass
                            answer = raw_crafted
                        except Exception:
                            answer = answer + "\n\n" + "\n".join([f"Action exécutée : {u}" for u in confirmations])
                except Exception:
                    pass

                try:
                    answer = normalize_model_output(answer)
                except Exception:
                    answer = str(answer)

                return {"answer": answer, "action_results": action_results}
            except Exception as e:
                logger.error(f"Error while checking/executing actions: {e}")
                try:
                    answer = normalize_model_output(answer)
                except Exception:
                    answer = str(answer)
                return {"answer": answer, "action_results": [{"status": "error", "error": "Action execution failed"}]}
        else:
            # Non-actionnable agents: do not attempt function-calling or action execution; return the original answer
"""
