from typing import Any

def execute_job(job_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    if job_type == "sum_numbers":
        numbers = payload.get("numbers")
        if not isinstance(numbers, list) or not numbers or any(
            isinstance(n, bool) or not isinstance(n, (int, float)) for n in numbers
        ):
            raise ValueError("numbers must be a nonempty list of numbers")
        return {"sum": sum(numbers)}

    if job_type == "word_count":
        text = payload.get("text")
        if not isinstance(text, str):
            raise ValueError("text must be a string")
        return {"count": len(text.split())}

    raise ValueError(f"unsupported job_type: {job_type}")
