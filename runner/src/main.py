import asyncio
import json
import time
from typing import Optional, Dict, Any
from job_processor import JobProcessor

class SQSRunner:
    def __init__(self):
        self.processor = JobProcessor()
        self.mock_mode = True
        self.running = False
        # Mock job queue for testing
        self.mock_jobs = []
    
    def add_mock_job(self, job_data: Dict[str, Any]):
        """Add a job to mock queue (for testing)"""
        print(f"📥 [RUNNER] Received job: {job_data['job_id']}")
        self.mock_jobs.append(job_data)
    
    async def poll_sqs(self) -> Optional[Dict[str, Any]]:
        """Poll SQS for new jobs (mocked for now)"""
        if self.mock_mode:
            if self.mock_jobs:
                return self.mock_jobs.pop(0)
            return None
        
        # TODO: Real SQS polling
        # messages = sqs.receive_message(QueueUrl=queue_url)
        return None
    
    async def run(self):
        """Main runner loop"""
        print("🚀 [RUNNER] Starting CodeVox runner...")
        print("🔄 [RUNNER] Polling for jobs...")
        
        self.running = True
        
        while self.running:
            try:
                # Poll for new job
                job_data = await self.poll_sqs()
                
                if job_data:
                    print(f"📋 [RUNNER] Processing job {job_data['job_id']}")
                    
                    # Process the job
                    result = await self.processor.process_job(job_data)
                    
                    # Send results back to API
                    callback_success = await self.processor.send_callback(result)
                    
                    if callback_success:
                        print(f"✅ [RUNNER] Job {job_data['job_id']} completed successfully")
                    else:
                        print(f"❌ [RUNNER] Job {job_data['job_id']} failed to send callback")
                else:
                    # No jobs available, wait before polling again
                    await asyncio.sleep(5)
                    
            except KeyboardInterrupt:
                print("\n🛑 [RUNNER] Shutting down...")
                self.running = False
                break
            except Exception as e:
                print(f"❌ [RUNNER] Error: {e}")
                await asyncio.sleep(10)  # Wait before retrying

# Test runner with mock job
async def main():
    runner = SQSRunner()
    
    # Add a mock job (simulating what SQS would provide)
    mock_job = {
        "job_id": "test-runner-123",
        "user_id": "mock-user-123", 
        "repo": "git@github.com:user/demo-project.git",
        "task_text": "Add a --help flag to the CLI tool",
        "branch": "main",
        "style_guide": "PEP8, use argparse, avoid globals"
    }
    
    runner.add_mock_job(mock_job)
    
    # Run the runner
    await runner.run()

if __name__ == "__main__":
    asyncio.run(main())