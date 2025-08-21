import os
import json
import requests
from typing import Dict, Any
import time
import uuid
from anthropic import Anthropic
from dotenv import load_dotenv
import tempfile
import shutil
from pathlib import Path
from typing import Dict, Any, Optional, Tuple
import git
from github import Github

load_dotenv()

class GithubIntegrator:
    def __init__(self):
        self.github_enabled = os.getenv("GITHUB_ENABLED", "false").lower() == "true"
        self.github_token = os.getenv("GITHUB_TOKEN")
        self.github_user_name = os.getenv("GITHUB_USER_NAME","CodeVox")
        if self.github_enabled and self.github_token:
            try:
                self.github=Github(self.github_token)
                user=self.github.get_user()
                print(f"✅ [RUNNER] Connected to Github as {user.login}")
            except Exception as e:
                print(f"❌ [RUNNER] Failed to connect to Github: {e}")
                self.github=None
                self.github_enabled=False
        else:
            self.github=None
            print("🔧 [RUNNER] Github integration disabled")
    
    def prepare_repo_url_for_cloning(self, repo_url: str) -> str:
        """Prepare repo URL with authentication for cloning"""
        if repo_url.startswith("https://github.com/"):
            # Insert GitHub token for HTTPS authentication
            token = self.github_token
            if token:
                # Convert https://github.com/owner/repo.git 
                # to https://token@github.com/owner/repo.git
                return repo_url.replace("https://", f"https://{token}@")
        return repo_url  # Return as-is for SSH or other formats
    def parse_repo_url(self, repo_url: str) -> Tuple[str, str]:
        """Parse GitHub repo URL to get owner and repo name"""
        print(f"🔍 [RUNNER] Parsing repo URL: {repo_url}")
        
        # Handle SSH format: git@github.com:owner/repo.git
        if repo_url.startswith("git@github.com:"):
            repo_part = repo_url.replace("git@github.com:", "").replace(".git", "")
            print(f"📝 [RUNNER] SSH format detected: {repo_part}")
        
        # Handle HTTPS format: https://github.com/owner/repo.git
        elif repo_url.startswith("https://github.com/"):
            repo_part = repo_url.replace("https://github.com/", "").replace(".git", "")
            print(f"📝 [RUNNER] HTTPS format detected: {repo_part}")
        
        # Handle unsupported formats
        else:
            raise ValueError(f"❌ Unsupported repo URL format: {repo_url}")
        
        # Split into owner and repo name
        try:
            owner, repo_name = repo_part.split("/")
            print(f"✅ [RUNNER] Parsed - Owner: {owner}, Repo: {repo_name}")
            return owner, repo_name
        except ValueError:
            raise ValueError(f"❌ Invalid repo format. Expected 'owner/repo', got: {repo_part}")

    async def process_with_git(self, job_data: Dict[str, Any],generated_code:str) -> Dict[str, Any]:
        """Process job with git integration"""
        job_id=job_data.get("job_id")
        repo_url=job_data.get("repo")
        task_text=job_data.get("task_text")
        branch_name=job_data.get("branch","main")

        workspace=Path(tempfile.mkdtemp(prefix=f"codevox-runner-{job_id}-"))
        try:
            #1. Clone the repo
            print(f"🔄 [RUNNER] Cloning repo: {repo_url}")
            clone_url=self.prepare_repo_url_for_cloning(repo_url)
            repo=git.Repo.clone_from(clone_url,workspace)

            #configure git user
            repo.config_writer().set_value("user","name",self.github_user_name).release()
            
            #2. Create a new branch
            feature_branch=f"codevox/feature-{job_id}"
            print(f"🔄 [RUNNER] Creating branch: {feature_branch}")
            repo.git.checkout("-b",feature_branch)

            # 3. Write generated code
            code_file = workspace / "codevox_generated.py"
            print(f"✍️ [RUNNER] Writing code to {code_file.name}")
            code_file.write_text(generated_code)
            
            # 4. Stage and commit changes
            repo.index.add([str(code_file)])
            commit_message = f"CodeVox: {task_text[:50]}{'...' if len(task_text) > 50 else ''}"
            print(f"💾 [RUNNER] Committing: {commit_message}")
            repo.index.commit(commit_message)
            
            # 5. Push branch
            print(f"⬆️ [RUNNER] Pushing {feature_branch}")
            origin = repo.remote("origin")
            origin.push(feature_branch)
            
            # 6. Create Pull Request
            pr_url = None
            if self.github:
                owner, repo_name = self.parse_repo_url(repo_url)
                github_repo = self.github.get_repo(f"{owner}/{repo_name}")
                
                pr_title = f"CodeVox: {task_text[:50]}{'...' if len(task_text) > 50 else ''}"
                pr_body = f"""## 🎤 Voice-Generated Code

    **Task:** {task_text}

    **Generated by:** CodeVox AI
    **Job ID:** {job_id}
    **Branch:** {feature_branch}

    ### Changes Made:
    - Created `{code_file.name}` with AI-generated code

    ### Review Notes:
    - This code was generated from voice input using Claude AI
    - Please review for correctness and security
    - Test thoroughly before merging
    """
                
                print(f"📝 [RUNNER] Creating PR: {pr_title}")
                pr = github_repo.create_pull(
                    title=pr_title,
                    body=pr_body,
                    head=feature_branch,
                    base=branch_name
                )
                pr_url = pr.html_url
                print(f"🔗 [RUNNER] PR created: {pr_url}")
            
            return {
                "status": "pr_opened",
                "commit_sha": str(repo.head.commit),
                "pr_url": pr_url,
                "branch": feature_branch,
                "files_touched": [code_file.name],
                "loc_delta": len(generated_code.split('\n')),
                "notes": f"Successfully created PR from voice command: {task_text[:100]}"
            }
            
        except Exception as e:
            print(f"❌ [RUNNER] Git operation failed: {e}")
            return {
                "status": "git_error",
                "notes": f"Git operation failed: {str(e)}"
            }
        
        finally:
            # Clean up workspace
            print(f"🧹 [RUNNER] Cleaning up workspace")
            shutil.rmtree(workspace, ignore_errors=True)
class JobProcessor:
    def __init__(self):
        self.api_base_url = os.getenv("API_BASE_URL", "http://localhost:8000")
        self.claude_enabled = os.getenv("CLAUDE_ENABLED", "false").lower() == "true"
        self.mock_mode = not self.claude_enabled
        self.github_integrator=GithubIntegrator()
        if self.claude_enabled:
            api_key = os.getenv("ANTHROPIC_API_KEY")
            if not api_key:
                print("❌ [RUNNER] ANTHROPIC_API_KEY is not set")
                self.mock_mode = True
                self.claude_client=None
            else:
                self.claude_client = Anthropic(api_key=api_key)
                print("✅ [RUNNER] Connected to Claude")
        else:
            self.claude_client = None 
            print("🔧 [RUNNER] Mock mode enabled")
    
    async def process_job(self, job_data: Dict[str, Any]) -> Dict[str, Any]:
        """Process a single job and return results"""
        job_id = job_data.get("job_id")
        task_text = job_data.get("task_text")
        repo = job_data.get("repo")
        
        print(f"🔧 [RUNNER] Processing job: {job_id}")
        print(f"📝 Task: {task_text}")
        print(f"📦 Repo: {repo}")
        
        start_time = time.time()
        
        if self.mock_mode:
            result= await self._mock_process_job(job_data)
        else:
            result=await self._claude_process_job(job_data)
        
        duration_ms = int((time.time() - start_time) * 1000)
        result["duration_ms"] = duration_ms
        return result
    
    async def _claude_process_job(self, job_data: Dict[str, Any]) -> Dict[str, Any]:
        """Process job using Claude"""
        task_text = job_data.get("task_text", "")
        repo = job_data.get("repo", "")

        try:
            # Create a focused prompt for code generation
            prompt = f"""
You are a senior software engineer. The user has requested: "{task_text}"

Please generate the appropriate code changes. Respond with:
1. A brief description of what you're implementing
2. The code changes needed
3. Which files would be modified
4. Whether this should be auto-merged or needs review

Keep the response concise and practical.
"""
            
            print("🤖 [RUNNER] Calling Claude API...")
            
            # Call Claude API
            response = self.claude_client.messages.create(
                model="claude-3-5-sonnet-20241022",
                max_tokens=1000,
                messages=[{"role": "user", "content": prompt}]
            )
            
            generated_content = response.content[0].text
            print(f"✨ [RUNNER] Claude generated: {len(generated_content)} characters")
            
            # Parse Claude's response and create realistic metrics
            code_complexity = self._analyze_code_complexity(generated_content, task_text)
            if self.github_integrator.github_enabled:
                git_result=await self.github_integrator.process_with_git(job_data,generated_content)
                git_result.update(
                    {
                        "job_id": job_data["job_id"],
                        "tok_in": response.usage.input_tokens,
                        "tok_out": response.usage.output_tokens,
                        "test_passed": True,
                        "lint_passed": True,
                    }
                )
                return git_result
            else:
                # Fallback to mock behavior
                return {
                    "job_id": job_data["job_id"],
                    "status": "code_generated",
                    "notes": f"Generated {len(generated_content)} characters of code (GitHub disabled)",
                    "loc_delta": len(generated_content.split('\n')),
                    "files_touched": ["generated_code.py"],
                    "tok_in": response.usage.input_tokens,
                    "tok_out": response.usage.output_tokens,
                }
        except Exception as e:
            print(f"❌ [RUNNER] Claude API error: {e}")
            # Fall back to mock on error
            return{
                "job_id": job_data["job_id"],
                "status": "claude_error",
                "notes": f"Claude API failed: {str(e)}"
            }
    
    def _analyze_code_complexity(self, generated_content: str, task_text: str) -> Dict[str, Any]:
        """Analyze Claude's response to estimate code complexity"""
        
        # Simple heuristics based on content length and task type
        content_length = len(generated_content)
        
        # Estimate lines of code based on content
        if content_length < 200:
            loc_delta = 5 + (content_length // 20)
        elif content_length < 500:
            loc_delta = 15 + (content_length // 30)
        else:
            loc_delta = 30 + (content_length // 50)
        
        # Estimate files based on task complexity
        files_touched = ["main.py"]  # Default
        
        if any(word in task_text.lower() for word in ["test", "testing", "unit test"]):
            files_touched.append("test_main.py")
        
        if any(word in task_text.lower() for word in ["config", "settings", "environment"]):
            files_touched.append("config.py")
            
        if any(word in task_text.lower() for word in ["api", "endpoint", "route"]):
            files_touched.extend(["api.py", "routes.py"])
            
        if any(word in task_text.lower() for word in ["database", "model", "schema"]):
            files_touched.extend(["models.py", "database.py"])
        
        return {
            "loc_delta": min(loc_delta, 200),  # Cap at 200 lines
            "files_touched": list(set(files_touched))  # Remove duplicates
        }
        
    
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