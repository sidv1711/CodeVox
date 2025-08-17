import os
import json
import requests
from typing import Dict, Any
import time
import uuid

class JobProcessor:
    def __init__(self):
        self.api_base_url = os.getenv("API_BASE_URL", "http://localhost:8000")
        self.mock_mode = True
    
    async def process_job(self, job_data: Dict[str, Any]) -> Dict[str, Any]:
        """Process a single job and return results"""
        job_id = job_data.get("job_id")
        task_text = job_data.get("task_text")
        repo = job_data.get("repo")
        
        print(f"🔧 [RUNNER] Processing job: {job_id}")
        print(f"📝 Task: {task_text}")
        print(f"📦 Repo: {repo}")
        
        # Simulate processing time
        time.sleep(2)
        
        if self.mock_mode:
            return await self._mock_process_job(job_data)
        
        # TODO: Real processing
        return {"status": "failed", "notes": "Real processing not implemented"}
    
    async def _mock_process_job(self, job_data: Dict[str, Any]) -> Dict[str, Any]:
        """Mock job processing for development"""
        task_text = job_data.get("task_text", "")
        
        # Mock different outcomes based on task content
        if "help" in task_text.lower():
            return {
                "job_id": job_data["job_id"],
                "status": "auto_merged",
                "commit_sha": f"abc{str(uuid.uuid4())[:6]}",
                "loc_delta": 15,
                "files_touched": ["cli.py", "README.md"],
                "tests_passed": True,
                "lint_passed": True,
                "tok_in": 1200,
                "tok_out": 400,
                "duration_ms": 2000,
                "notes": "Added --help flag with documentation"
            }
        elif "stdin" in task_text.lower():
            return {
                "job_id": job_data["job_id"],
                "status": "auto_merged", 
                "commit_sha": f"def{str(uuid.uuid4())[:6]}",
                "loc_delta": 25,
                "files_touched": ["cli.py", "tests/test_cli.py"],
                "tests_passed": True,
                "lint_passed": True,
                "tok_in": 1500,
                "tok_out": 600,
                "duration_ms": 2500,
                "notes": "Added --stdin flag with input handling"
            }
        else:
            # Mock a case that needs PR approval
            return {
                "job_id": job_data["job_id"],
                "status": "pr_opened",
                "pr_url": f"https://github.com/user/repo/pull/{job_data['job_id'][:8]}",
                "loc_delta": 150,  # Too many lines for auto-merge
                "files_touched": ["cli.py", "utils.py", "tests/test_cli.py"],
                "tests_passed": True,
                "lint_passed": True,
                "tok_in": 2000,
                "tok_out": 800,
                "duration_ms": 3500,
                "notes": "Added verbose logging - needs review due to size"
            }
    
    async def send_callback(self, result: Dict[str, Any]) -> bool:
        """Send results back to API"""
        callback_url = f"{self.api_base_url}/api/v1/callback/runner-status"
        
        try:
            response = requests.post(callback_url, json=result, timeout=10)
            if response.status_code == 200:
                print(f"✅ [RUNNER] Callback sent successfully")
                return True
            else:
                print(f"❌ [RUNNER] Callback failed: {response.status_code}")
                return False
        except Exception as e:
            print(f"❌ [RUNNER] Callback error: {e}")
            return False