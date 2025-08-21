import asyncio
import json
import os
import time
from typing import Optional, Dict, Any, Tuple
from job_processor import JobProcessor
from dotenv import load_dotenv

import boto3
from botocore.config import Config

load_dotenv()

class SQSRunner:
    def __init__(self):
        self.processor = JobProcessor()
        self.mock_mode = os.getenv("SQS_ENABLED", "false").lower() != "true"
        self.running = False
        # Mock queue (only used when mock_mode is True)
        self.mock_jobs = []

        # Real SQS client when enabled
        if not self.mock_mode:
            self.queue_url = os.getenv("SQS_QUEUE_URL")
            if not self.queue_url:
                raise ValueError("SQS_QUEUE_URL is required when SQS_ENABLED=true")
            region = os.getenv("AWS_DEFAULT_REGION", "us-east-1")
            self.sqs = boto3.client(
                "sqs",
                region_name=region,
                config=Config(retries={"max_attempts": 3})
            )
            print(f"🔗 [RUNNER] Connected to SQS: {self.queue_url}")
        else:
            self.sqs = None

    def add_mock_job(self, job_data: Dict[str, Any]):
        """Add a job to mock queue (for testing)"""
        print(f"📥 [RUNNER] Received job: {job_data['job_id']}")
        self.mock_jobs.append(job_data)

    async def poll_sqs(self) -> Optional[Tuple[Dict[str, Any], Optional[str]]]:
        """Poll for a job. Returns (job_data, receipt_handle) or None."""
        if self.mock_mode:
            if self.mock_jobs:
                return self.mock_jobs.pop(0), None
            return None

        try:
            resp = self.sqs.receive_message(
                QueueUrl=self.queue_url,
                MaxNumberOfMessages=1,
                WaitTimeSeconds=10,     # long polling
                VisibilityTimeout=60    # time to process before message reappears
            )
            messages = resp.get("Messages", [])
            if not messages:
                return None

            msg = messages[0]
            body = msg.get("Body", "{}")
            job_data = json.loads(body)
            receipt = msg.get("ReceiptHandle")
            return job_data, receipt
        except Exception as e:
            print(f"❌ [RUNNER] SQS receive error: {e}")
            await asyncio.sleep(5)
            return None
    
    async def run(self):
        """Main runner loop"""
        print("🚀 [RUNNER] Starting CodeVox runner...")
        print("🔄 [RUNNER] Polling for jobs...")
        
        self.running = True
        
        while self.running:
            try:
                polled = await self.poll_sqs()
                if polled:
                    job_data, receipt = polled
                    print(f"📋 [RUNNER] Processing job {job_data['job_id']}")

                    # Process the job
                    result = await self.processor.process_job(job_data)
                    
                    # Send results back to API
                    callback_success = await self.processor.send_callback(result)
                    
                    if callback_success:
                        print(f"✅ [RUNNER] Job {job_data['job_id']} completed successfully")
                        # Delete message if using real SQS
                        if not self.mock_mode and receipt:
                            try:
                                self.sqs.delete_message(QueueUrl=self.queue_url, ReceiptHandle=receipt)
                                print(f"🗑️  [RUNNER] Deleted message for job {job_data['job_id']}")
                            except Exception as e:
                                print(f"⚠️ [RUNNER] Failed to delete message: {e}")
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
    
    # Only seed mock job when SQS is disabled
    if runner.mock_mode:
        mock_job = {
            "job_id": "test-runner-123",
            "user_id": "00000000-0000-0000-0000-000000000000",
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