import json
import pandas as pd
import numpy as np

from src.classes.packet import EventType
from src.classes.helper import Helper
from src.metrics.stateless_accuracy import smart_list_contains


class Accuracy:
    @staticmethod
    def calculate(session_id: str, entry, **kwargs):
        transcript = Helper.read_transcript(session_id)
        parsed_messages = [json.loads(item["message"]) for item in transcript]

        ground_truth_outputs = entry.get("outputs", [])
        ground_truth_actions = entry.get("actions", [])

        conversation_actions = []
        for parsed in parsed_messages:
            if parsed.get("event") == EventType.RESPONSE_FUNCTION_CALL:
                function_call = parsed.get("function_call")
                if function_call and isinstance(function_call.get("arguments"), str):
                    try:
                        function_call["arguments"] = json.loads(function_call["arguments"])
                    except json.JSONDecodeError:
                        pass
                if function_call:
                    conversation_actions.append(function_call)

        last_runtime_hash = next(
            (item for item in reversed(parsed_messages)
             if item.get("event") == EventType.RESPONSE_FUNCTION_CALL_RESULT
             and item.get("hash")),
            None
        )

        last_ground_truth_hash  = next(
            (item for item in reversed(parsed_messages)
             if item.get("event") == EventType.BENCHFORCE_LOG_DRYRUN_DB
             and item.get("hash")),
            None
        )

        last_original_hash = next(
            (item for item in reversed(parsed_messages)
             if item.get("event") == EventType.BENCHFORCE_LOG_ORIG_DB
             and item.get("hash")),
            None
        )

        terminated = next(
            (item for item in parsed_messages
             if item.get("event") == EventType.BENCHFORCE_TERMINATE),
            None
        )

        runtime_hash = last_runtime_hash.get("hash") if last_runtime_hash else None
        ground_truth_hash = last_ground_truth_hash.get("hash") if last_ground_truth_hash else None
        original_hash = last_original_hash.get("hash") if last_original_hash else None

        agent_text_outputs = " ".join([
            parsed_messages[i].get("text")
            for i, item in enumerate(transcript)
            if item["role"] == "agent" and parsed_messages[i].get("event")
               in [EventType.RESPONSE_TEXT_DONE, EventType.RESPONSE_AUDIO_TRANSCRIPT_DONE]
        ])

        accuracy = 0

        total_outputs = len(ground_truth_outputs)
        matched_outputs = 0

        if total_outputs > 0:
            agent_text_outputs_lower = agent_text_outputs.lower()
            available_text = agent_text_outputs_lower
            processed_ground_truth = [str(item).lower() for item in ground_truth_outputs if isinstance(item, str)]
            for expected_output in processed_ground_truth:
                idx = available_text.find(expected_output)
                if idx != -1:
                    matched_outputs += 1
                    available_text = available_text[:idx] + " " * len(expected_output) + available_text[idx+len(expected_output):]

            accuracy = 1 if total_outputs == matched_outputs else 0

        elif ground_truth_actions:
            accuracy = 1 if smart_list_contains(ground_truth_actions, conversation_actions) else 0

        elif runtime_hash and ground_truth_hash and original_hash:
            accuracy = 1 if runtime_hash == ground_truth_hash else 0

        return {"session_id": session_id, "accuracy": accuracy, "terminated": True if terminated else False}


    @staticmethod
    def aggregate(results):
        total_tasks = len(results)
        finished_tasks = sum(1 for r in results if r.get("terminated"))
        all_scores = [r["accuracy"] for r in results]
        finished_scores = [r["accuracy"] for r in results if r.get("terminated")]

        accuracy_all = np.mean(all_scores) if all_scores else 0
        accuracy_finished = np.mean(finished_scores) if finished_scores else 0

        aggregated_data = {
            "Total entries": total_tasks,
            "Finished entries": finished_tasks,
            "Accuracy (All)": accuracy_all,
            "Accuracy (Finished)": accuracy_finished
        }

        json_results = {
            "total_entries": total_tasks,
            "finished_entries": finished_tasks,
            "accuracy_all": float(accuracy_all),
            "accuracy_finished": float(accuracy_finished)
        }

        df = pd.DataFrame([aggregated_data])
        return df, json_results
