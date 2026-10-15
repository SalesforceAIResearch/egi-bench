"""
Command Line Interface for LoCoBench
"""

import click
import logging
import os
import sys
import json
import time
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from typing import List, Dict, Any

from .core.config import Config
from .core.task import TaskCategory, DifficultyLevel
from .generation.synthetic_generator import CriticalAuthError


# Surface httpx's per-request log line (matches HERB / MCPEval / MCP-Universe
# / UserBench / PersonaBench / CRMArena). LoCoBench is special: the
# ``locobench.generation`` logger already has its own console+file handlers
# wired by ``setup_generation_logging`` and propagates to root by default,
# so we deliberately do NOT call ``logging.basicConfig`` here -- doing so
# would print every ``locobench.generation`` line twice. Instead, attach a
# dedicated stderr handler directly to the ``httpx`` logger and silence its
# propagation, leaving every other logger untouched. ``httpcore`` stays at
# WARNING so its low-level connection-pool noise does not flood the log.
_httpx_logger = logging.getLogger("httpx")
_httpx_logger.setLevel(logging.INFO)
if not _httpx_logger.handlers:
    _httpx_handler = logging.StreamHandler(sys.stderr)
    _httpx_handler.setFormatter(
        logging.Formatter("%(levelname)s:%(name)s:%(message)s")
    )
    _httpx_logger.addHandler(_httpx_handler)
_httpx_logger.propagate = False
logging.getLogger("httpcore").setLevel(logging.WARNING)

console = Console()


def save_progress(progress_file: Path, completed_projects: List[Dict[str, Any]], phase: str):
    """Save progress to a JSON file for resumability"""
    with open(progress_file, 'w') as f:
        json.dump({
            'phase': phase,
            'timestamp': str(datetime.now()),
            'completed_projects': completed_projects,
            'total_completed': len(completed_projects)
        }, f, indent=2)

def load_progress(progress_file: Path) -> List[Dict[str, Any]]:
    """Load progress from a JSON file"""
    if not progress_file.exists():
        return []
    
    try:
        with open(progress_file, 'r') as f:
            data = json.load(f)
            return data.get('completed_projects', [])
    except Exception as e:
        console.print(f"⚠️ Warning: Could not load progress file: {e}")
        return []


def save_timing_summary(phase_name, start_time, end_time, stats):
    """Save timing summary data for analysis"""
    timing_file = Path(f"logs/timing_phase{phase_name}.json")
    timing_file.parent.mkdir(exist_ok=True)
    
    timing_data = {
        'phase': phase_name,
        'start_time': start_time.isoformat(),
        'end_time': end_time.isoformat(),
        'duration_seconds': (end_time - start_time).total_seconds(),
        'stats': stats,
        'timestamp': datetime.now().isoformat()
    }
    
    with open(timing_file, 'w') as f:
        json.dump(timing_data, f, indent=2)


@click.group()
@click.version_option(version="0.1.0", prog_name="LoCoBench")
@click.pass_context  
def main(ctx):
    """LoCoBench: A Novel Benchmark for Evaluating Long-Context LLMs in Software Development Tasks"""
    ctx.ensure_object(dict)


@main.command()
@click.option('--config-path', '-c', type=click.Path(), help='Path to configuration file')
@click.option('--save-config', '-s', type=click.Path(), help='Save configuration to file')
def setup(config_path, save_config):
    """Set up LoCoBench environment and configuration"""
    console.print(Panel.fit("🚀 LoCoBench Setup", style="bold blue"))
    
    try:
        # Load configuration
        config = Config.from_yaml(config_path)
        
        # Validate configuration
        errors = config.validate()
        
        if errors:
            console.print("❌ Configuration errors found:", style="bold red")
            for error in errors:
                console.print(f"  • {error}", style="red")
            
            # Check for available API keys
            
            if not any([config.api.openai_api_key, config.api.google_api_key, os.getenv("OPENAI_BASE_URL")]):
                console.print("\n💡 To fix API key issues, set environment variables:", style="yellow")
                console.print("  🏆 Recommended defaults:")
                console.print("  export OPENAI_API_KEY='your-key-here'   # Or any OpenAI-compatible key")
                console.print("  export GEMINI_API_KEY='your-key-here'   # Optional secondary model")
                console.print("  export OPENAI_BASE_URL='http://localhost:8008/v1'  # OpenAI-compatible proxy")
                
            sys.exit(1)
        
        # Display configuration summary
        console.print("✅ Configuration validated successfully!", style="bold green")
        console.print(config.summary())
        
        # Save configuration if requested
        if save_config:
            config.save_to_file(save_config)
            console.print(f"💾 Configuration saved to: {save_config}", style="green")
            
        console.print("🎯 Setup complete! Ready to begin LoCoBench benchmark generation.", style="bold green")
        
    except Exception as e:
        console.print(f"❌ Setup failed: {e}", style="bold red")
        sys.exit(1)


@main.command()
@click.option('--config-path', '-c', type=click.Path(), help='Path to configuration file')
def status(config_path):
    """Show current LoCoBench status and configuration"""
    try:
        config = Config.from_yaml(config_path)
        
        # Create status table
        table = Table(title="LoCoBench Status", style="cyan")
        table.add_column("Component", style="bold")
        table.add_column("Status", justify="center") 
        table.add_column("Details")
        
        # API status (checking our 2 Elite Models)
        
        apis = [
            ("OpenAI", config.api.openai_api_key),
            ("Google", config.api.google_api_key),
            # Removed HuggingFace - no longer needed with synthetic generation
        ]
        
        for name, key in apis:
            status_icon = "✅" if key else "❌"
            status_text = "Configured" if key else "Missing"
            table.add_row(f"{name} API", status_icon, status_text)
        
        # OpenAI-compatible endpoint status
        openai_base_url = os.getenv("OPENAI_BASE_URL")
        base_url_status_icon = "✅" if openai_base_url else "❌"
        base_url_status_text = openai_base_url if openai_base_url else "Missing"
        table.add_row("OpenAI-Compatible Base URL", base_url_status_icon, base_url_status_text)
        
        # Directory status
        directories = [
    
            ("Output Directory", config.data.output_dir), 
            ("Generated Directory", config.data.generated_dir)
        ]
        
        for name, path in directories:
            exists = Path(path).exists()
            status_icon = "✅" if exists else "❌"
            status_text = f"{'Exists' if exists else 'Missing'}: {path}"
            table.add_row(name, status_icon, status_text)
        
        # Benchmark configuration
        table.add_row("Benchmark Scale", "📊", f"{config.phase3.total_instances:,} instances")
        table.add_row("Task Categories", "📋", f"{len(config.phase3.task_distribution)} categories")
        table.add_row("Languages", "🔤", f"{len(config.phase1.supported_languages)} languages")
        
        console.print(table)
        
        # Validation errors
        errors = config.validate()
        if errors:
            console.print("\n⚠️  Configuration Issues:", style="yellow")
            for error in errors:
                console.print(f"  • {error}", style="yellow")
        else:
            console.print("\n✅ All systems ready!", style="bold green")
            
    except Exception as e:
        console.print(f"❌ Status check failed: {e}", style="bold red")
        sys.exit(1)


@main.command()
@click.option('--config-path', '-c', type=click.Path(), help='Path to configuration file')
@click.option('--phase', type=click.Choice(['1', '2', '3', '4', 'all']), default='1', 
              help='Which implementation phase to run')
@click.option('--dry-run', is_flag=True, help='Show what would be done without executing')
@click.option('--force', is_flag=True, help='Force regeneration of already completed projects')
@click.option('--max-concurrent', '-j', type=int, default=3, 
              help='Maximum concurrent operations (default: 3, recommended: 3-10)')
def generate(config_path, phase, dry_run, force, max_concurrent):
    """Generate LoCoBench benchmark instances"""
    console.print(Panel.fit(f"🏗️  LoCoBench Generation - Phase {phase}", style="bold green"))
    
    if dry_run:
        console.print("🔍 DRY RUN MODE - No actual generation will occur", style="yellow")
    
    if max_concurrent > 1:
        console.print(f"🚀 Parallel mode: {max_concurrent} concurrent operations", style="bold blue")
    
    try:
        config = Config.from_yaml(config_path)
        
        # Validate configuration
        errors = config.validate()
        if errors:
            console.print("❌ Configuration errors found:", style="bold red")
            for error in errors:
                console.print(f"  • {error}", style="red")
            sys.exit(1)
        
        if phase == '1' or phase == 'all':
            console.print("🎯 Phase 1: Synthetic Project Generation", style="bold")
            if not dry_run:
                import asyncio
                from .generation.synthetic_generator import SyntheticProjectGenerator, ProjectDomain, ProjectComplexity
                asyncio.run(run_phase_1_generation(config, max_concurrent))
            else:
                console.print("  • Generate synthetic multi-file projects")
                console.print(f"  • 10 domains × 4 complexity levels × {len(config.phase1.supported_languages)} languages")
                console.print("  • Production-quality code with tests & docs")
                target_projects = len(config.phase1.supported_languages) * config.phase1.projects_per_language
                console.print(f"  • Target: {target_projects:,} synthetic projects")
                
        if phase == '2' or phase == 'all':
            console.print("🎯 Phase 2: Synthetic Codebase Generation", style="bold")
            if not dry_run:
                import asyncio
                asyncio.run(run_phase_2_generation(config, force, max_concurrent))
            else:
                console.print("  • Generate actual code files from specifications")
                console.print("  • Multi-file projects with realistic complexity")
                console.print("  • Tests, documentation, and error handling")
                
        if phase == '3' or phase == 'all':
            console.print("🎯 Phase 3: Long-Context Evaluation Scenario Creation", style="bold")
            if not dry_run:
                import asyncio
                asyncio.run(run_phase_3_generation(config, force, max_concurrent))
            else:
                console.print("  • Create evaluation scenarios from generated code")
                console.print(f"  • {len(config.phase3.task_distribution)} task categories × varying difficulties")
                console.print("  • Context-rich scenarios for long-context evaluation")
                
        if phase == '4' or phase == 'all':
            console.print("🎯 Phase 4: Automated Test-Driven Validation", style="bold")
            if not dry_run:
                import asyncio
                asyncio.run(run_phase_4_generation(config, force, max_concurrent))
            else:
                console.print("  • Generate automated test suites")
                console.print("  • Compilation, unit tests, integration tests")
                console.print(f"  • {len(config.phase4.software_engineering_weights)} software engineering metrics (ACS, DTA, CFRD, STS, RS, CS, IS, SES)")
                console.print("  • Security analysis and code quality validation")
                
        console.print("\n✅ Generation complete!", style="bold green")
        console.print("Next steps:")
        console.print("  • Run evaluation: locobench evaluate")
        console.print("  • Check status: locobench status")
        
    except Exception as e:
        console.print(f"❌ Generation failed: {e}", style="bold red")
        sys.exit(1)


@main.command()
@click.option('--config-path', '-c', type=click.Path(), help='Path to configuration file')
@click.option('--model', '-m', multiple=True, help='Model to evaluate (can specify multiple)')
@click.option('--task-category', '-t', multiple=True, help='Task category to evaluate')
@click.option('--difficulty', '-d', type=click.Choice(['easy', 'medium', 'hard', 'expert']),
              help='Difficulty level to evaluate')
@click.option('--output-file', '-o', type=click.Path(), help='Output file for results (auto-generated if not specified)')
@click.option('--no-save', is_flag=True, help='Skip saving results to file (display only)')
@click.option('--no-resume', is_flag=True, help='Start fresh evaluation (ignore any existing checkpoint)')
@click.option('--parallel', is_flag=True, help='Enable parallel model evaluation (faster but more resource intensive)')
@click.option('--max-concurrent-models', type=int, default=2, help='Maximum number of models to evaluate concurrently (default: 2)')
@click.option('--max-concurrent-scenarios', type=int, default=1, help='Maximum number of scenarios per model to evaluate concurrently (default: 1)')
@click.option('--monitor', is_flag=True, help='Start web monitoring dashboard at http://localhost:8080')
def evaluate(config_path, model, task_category, difficulty, output_file, no_save, no_resume, parallel, max_concurrent_models, max_concurrent_scenarios, monitor):
    """Evaluate models on LoCoBench benchmark"""
    console.print(Panel.fit("🧪 LoCoBench Evaluation", style="bold purple"))
    
    # Start monitoring dashboard if requested
    dashboard = None
    if monitor:
        try:
            from .evaluation.monitoring import MonitoringDashboard
            dashboard = MonitoringDashboard()
            dashboard.start()
        except Exception as e:
            console.print(f"⚠️  Failed to start monitoring dashboard: {e}", style="yellow")
    
    try:
        config = Config.from_yaml(config_path)
        
        from .evaluation.evaluator import run_evaluation
        evaluation_data = run_evaluation(config, model, task_category, difficulty, resume=not no_resume, parallel=parallel, max_concurrent_models=max_concurrent_models, max_concurrent_scenarios=max_concurrent_scenarios)
        
        # Check if evaluation succeeded
        if not evaluation_data.get('success', False):
            console.print(f"❌ Evaluation failed: {evaluation_data.get('error', 'Unknown error')}", style="bold red")
            return
        
        # Extract results
        evaluator = evaluation_data['evaluator']
        results = evaluation_data['results']
        summaries = evaluation_data['summaries']
        
        # Auto-generate output filename if not provided
        if not output_file and not no_save:
            from datetime import datetime
            from pathlib import Path
            
            # Build descriptive filename
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            
            # Model names part
            model_list = list(model) if model else ['all-models']
            models_part = "_".join([m.replace('-', '').replace('_', '').lower() for m in model_list])
            if len(models_part) > 30:  # Limit length
                models_part = f"{len(model_list)}models"
            
            # Category part
            if task_category:
                categories_part = "_".join([c.replace('_', '') for c in task_category])
                if len(categories_part) > 20:
                    categories_part = f"{len(task_category)}cats"
            else:
                categories_part = "allcats"
            
            # Difficulty part
            difficulty_part = difficulty if difficulty else "alldiff"
            
            # Construct filename
            output_file = f"{models_part}_{categories_part}_{difficulty_part}_{timestamp}_evaluation_results.json"
            
            # Ensure results directory exists
            results_dir = Path("evaluation_results")
            results_dir.mkdir(exist_ok=True)
            output_file = results_dir / output_file
        
        # Show evaluation parameters (including auto-generated filename)
        console.print("📋 Evaluation Parameters:", style="bold")
        console.print(f"  • Models: {list(model) if model else 'All available'}")
        console.print(f"  • Categories: {list(task_category) if task_category else 'All categories'}")
        console.print(f"  • Difficulty: {difficulty if difficulty else 'All levels'}")
        if no_save:
            console.print(f"  • Output: Display only (saving disabled)")
        else:
            console.print(f"  • Output: {output_file}")
        
        # Display formatted results
        if summaries:
            console.print("\n📊 Evaluation Completed!", style="bold green")
            evaluator.display_results(summaries)
            
            # Save comprehensive results (unless explicitly disabled)
            if not no_save:
                from pathlib import Path
                output_path = Path(output_file)
                evaluator.save_results(results, summaries, output_path)
        else:
            console.print("❌ No evaluation results generated", style="bold red")
        
    except Exception as e:
        console.print(f"❌ Evaluation failed: {e}", style="bold red")
        sys.exit(1)
    finally:
        # Clean up monitoring dashboard
        if dashboard:
            dashboard.stop()


@main.command()
def version():
    """Show LoCoBench version information"""
    console.print("🔧 LoCoBench v0.1.0", style="bold blue")
    console.print("A Novel Benchmark for Evaluating Long-Context Language Models")
    console.print("in Software Development Tasks")
    console.print("\nFor more information: https://github.com/LoCoBench/LoCoBench")


async def run_phase_1_generation(config, max_concurrent=3):
    """Run Phase 1: Synthetic Project Generation with Guaranteed Uniqueness, progress tracking, and resumability"""
    from .generation.synthetic_generator import (
        SyntheticProjectGenerator, ProjectDomain, ProjectComplexity,
        ProjectArchitecture, ProjectTheme
    )
    import asyncio
    from asyncio import Semaphore
    
    # ⏰ START TIMING
    phase_start_time = time.time()
    phase_start_datetime = datetime.now()
    
    console.print("\n🎯 [bold]Synthetic Project Generation Pipeline (Uniqueness Guaranteed)[/bold]")
    console.print("=" * 75)
    console.print(f"⏰ Phase 1 started at: {phase_start_datetime.strftime('%Y-%m-%d %H:%M:%S')}")
    
    # Initialize timing tracking
    project_times = []
    estimated_total_time = None
    
    # Setup progress tracking
    progress_file = Path("logs/phase1_progress.json")
    progress_file.parent.mkdir(exist_ok=True)
    completed_projects = load_progress(progress_file)
    completed_project_names = {p.get('unique_id', '') for p in completed_projects}
    
    generator = SyntheticProjectGenerator(config, log_file="logs/phase1_generation.log")
    
    console.print(f"📋 Resume state: {len(completed_projects)} projects previously completed")
    
    # Target: projects per language from config
    languages = config.phase1.supported_languages
    projects_per_language = config.phase1.projects_per_language
    total_projects = len(languages) * projects_per_language
    
    # Get all available factors for uniqueness
    domains = list(ProjectDomain)
    complexities = list(ProjectComplexity)
    architectures = list(ProjectArchitecture)
    themes = list(ProjectTheme)
    
    console.print(f"📊 Target: {len(languages)} languages × {projects_per_language} projects = {total_projects} total")
    console.print(f"🌐 Languages: {', '.join(languages)}")
    console.print(f"🏗️ Uniqueness factors:")
    console.print(f"   • {len(domains)} domains × {len(complexities)} complexities × {len(architectures)} architectures × {len(themes)} themes")
    console.print(f"   • = {len(domains) * len(complexities) * len(architectures) * len(themes):,} possible combinations")
    console.print(f"   • + unique seeds = guaranteed uniqueness for {projects_per_language} projects per language ✅")
    
    if max_concurrent > 1:
        console.print(f"🚀 [bold blue]Parallel mode: {max_concurrent} concurrent specifications[/bold blue]")
    
    console.print("🏗️ Generating unique project specifications...")
    
    # Create complexity selection pool based on config distribution
    import random
    
    # 🔧 FIX: Set deterministic seed for reproducible generation
    random.seed(42)  # Fixed seed ensures same complexity assignment across runs
    
    complexity_pool = []
    for complexity_name, ratio in config.phase1.complexity_distribution.items():
        complexity_enum = getattr(ProjectComplexity, complexity_name.upper())
        count = int(projects_per_language * len(languages) * ratio)
        complexity_pool.extend([complexity_enum] * count)
    
    # Ensure we have exactly the right number of complexities
    while len(complexity_pool) < total_projects:
        complexity_pool.append(random.choice(complexities))
    while len(complexity_pool) > total_projects:
        complexity_pool.pop()
    
    # Shuffle for random distribution (now deterministic due to fixed seed)
    random.shuffle(complexity_pool)
    
    # Generate unique combinations for each language
    spec_tasks = []
    global_index = 0
    
    for language in languages:
        console.print(f"🔧 [cyan]Planning {projects_per_language} unique projects for {language}...[/cyan]")
        
        # Create unique combinations for this language
        language_combinations = []
        
        for i in range(projects_per_language):
            # Use different distribution strategies to ensure uniqueness
            domain = domains[i % len(domains)]
            complexity = complexity_pool[global_index]
            architecture = architectures[i % len(architectures)]
            theme = themes[i % len(themes)]
            
            # Create unique seed for deterministic but varied LLM generation
            unique_seed = hash(f"{language}-{domain.value}-{complexity.value}-{architecture.value}-{theme.value}-{i}") % 1000000
            
            # Generate unique project ID
            unique_id = f"{language}_{domain.value}_{complexity.value}_{i:03d}"
            
            language_combinations.append({
                'unique_id': unique_id,
                'language': language,
                'domain': domain,
                'complexity': complexity,
                'architecture': architecture,
                'theme': theme,
                'index': i,
                'seed': unique_seed,
                'global_index': global_index
            })
            
            global_index += 1
        
        # Add to spec tasks
        spec_tasks.extend(language_combinations)
        
        # Verify uniqueness for this language
        unique_combinations = set()
        for combo in language_combinations:
            combination_key = (combo['domain'].value, combo['complexity'].value, 
                             combo['architecture'].value, combo['theme'].value)
            unique_combinations.add(combination_key)
        
        console.print(f"   ✅ [green]{len(unique_combinations)} unique factor combinations for {language}[/green]")
    
    console.print(f"🎯 Generated {len(spec_tasks)} unique project specifications...")
    
    # Verify global uniqueness
    all_unique_ids = set(task['unique_id'] for task in spec_tasks)
    console.print(f"🔍 Uniqueness verification: {len(all_unique_ids)} unique IDs for {len(spec_tasks)} projects ✅")
    
    # Semaphore for parallel generation
    semaphore = Semaphore(max_concurrent)
    
    # Statistics tracking
    projects_generated = 0
    projects_failed = 0
    
    async def generate_single_spec(task_info, task_index):
        """Generate a single project specification with guaranteed uniqueness"""
        async with semaphore:
            unique_id = task_info['unique_id']
            language = task_info['language']
            domain = task_info['domain']
            complexity = task_info['complexity']
            architecture = task_info['architecture']
            theme = task_info['theme']
            seed = task_info['seed']
            
            # Skip if already completed (resume functionality)
            if unique_id in completed_project_names:
                console.print(f"✅ [green]Skipping {unique_id} - Already completed![/green]")
                return {
                    'success': True,
                    'skipped': True,
                    'unique_id': unique_id,
                    'project_name': unique_id
                }
            
            try:
                console.print(f"🔨 [bold cyan]Generating {task_index}/{len(spec_tasks)}: {unique_id}[/bold cyan]")
                console.print(f"     {language} | {domain.value} | {complexity.value} | {architecture.value} | {theme.value}")
                
                # Start timing
                import time
                start_time = time.time()
                
                # Set random seed for deterministic variation
                random.seed(seed)
                
                # Generate project specification with unique factors
                spec = await generator.generate_project_specification_unique(
                    domain, complexity, language, architecture, theme, unique_id, seed
                )
                
                generation_time = time.time() - start_time
                
                # Save specification to project directory  
                project_name = unique_id
                
                # Create project directory and save specification
                project_dir = generator.generated_dir / project_name
                project_dir.mkdir(exist_ok=True)
                
                # Save specification metadata
                metadata = {
                    "specification": spec.to_dict(),
                    "generated_timestamp": time.time(),
                    "phase_1_complete": True,
                    "uniqueness_factors": {
                        "domain": domain.value,
                        "complexity": complexity.value, 
                        "architecture": architecture.value,
                        "theme": theme.value,
                        "seed": seed
                    }
                }
                
                with open(project_dir / "project_metadata.json", 'w') as f:
                    import json
                    json.dump(metadata, f, indent=2)
                
                console.print(f"   ✅ [green]Generated {project_name}![/green] {spec.target_file_count} files, ~{spec.target_token_count:,} tokens ({generation_time:.1f}s)")
                
                # Save progress for successful completion
                current_progress = {
                    'unique_id': unique_id,
                    'project_name': project_name,
                    'status': 'completed',
                    'language': language,
                    'domain': domain.value,
                    'complexity': complexity.value,
                    'architecture': architecture.value,
                    'theme': theme.value,
                    'timestamp': time.time()
                }
                completed_projects.append(current_progress)
                save_progress(progress_file, completed_projects, "1")
                
                return {
                    'success': True,
                    'project_name': project_name,
                    'unique_id': unique_id,
                    'language': language,
                    'domain': domain.value,
                    'complexity': complexity.value,
                    'architecture': architecture.value,
                    'theme': theme.value,
                    'generation_time': generation_time,
                    'target_files': spec.target_file_count,
                    'target_tokens': spec.target_token_count
                }
                
            except CriticalAuthError as e:
                # Critical auth errors should stop the entire process
                console.print(f"   🚨 [bold red]CRITICAL AUTH FAILURE in {unique_id}[/bold red]")
                console.print(f"   🔑 {e.provider}: {e.message}")
                console.print("   🛑 [yellow]Stopping generation to fix authentication...[/yellow]")
                
                # Save current progress before stopping
                current_progress = {
                    'unique_id': unique_id,
                    'status': 'auth_failed',
                    'error': str(e),
                    'timestamp': time.time()
                }
                completed_projects.append(current_progress)
                save_progress(progress_file, completed_projects, "1")
                
                # Re-raise to stop the entire process
                raise e
                
            except Exception as e:
                console.print(f"   ❌ [red]Failed {unique_id}: {str(e)}[/red]")
                return {
                    'success': False,
                    'error': str(e),
                    'unique_id': unique_id,
                    'language': language,
                    'domain': domain.value
                }
    
    # Execute all specification generation tasks in parallel
    console.print(f"\n🚀 [bold]Starting parallel specification generation for {len(spec_tasks)} projects...[/bold]")
    
    try:
        # Create asyncio tasks
        tasks = []
        for i, task_info in enumerate(spec_tasks, 1):
            task = generate_single_spec(task_info, i)
            tasks.append(task)
        
        # Wait for all tasks to complete
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Check for CriticalAuthError in results
        for result in results:
            if isinstance(result, CriticalAuthError):
                raise result
        
        # Process results
        successful_projects = []
        failed_projects = []
        skipped_projects = 0
        
        for result in results:
            if isinstance(result, Exception):
                failed_projects.append(f"Exception: {str(result)}")
                projects_failed += 1
            elif result and result['success']:
                if result.get('skipped'):
                    skipped_projects += 1
                else:
                    successful_projects.append(result)
                    projects_generated += 1
                    # Collect timing data for analysis
                    if 'generation_time' in result:
                        project_times.append(result['generation_time'])
            else:
                failed_projects.append(f"{result['language']} {result['domain']}" if result else "Unknown project")
                projects_failed += 1
        
        # ⏰ TIMING ANALYSIS
        phase_end_time = time.time()
        phase_duration = phase_end_time - phase_start_time
        phase_end_datetime = datetime.now()
        
        # Convert to human readable (define globally for all timing displays)
        def format_duration(seconds):
            if seconds < 60:
                return f"{seconds:.1f}s"
            elif seconds < 3600:
                return f"{seconds/60:.1f}m"
            else:
                return f"{seconds/3600:.1f}h"
        
        # Calculate timing statistics
        if project_times:
            avg_project_time = sum(project_times) / len(project_times)
            min_project_time = min(project_times)
            max_project_time = max(project_times)
            total_generation_time = sum(project_times)
            
            # Calculate full-scale projections
            total_target_projects = len(config.phase1.supported_languages) * config.phase1.projects_per_language
            estimated_full_scale_time = avg_project_time * total_target_projects
            
            # Estimate parallel efficiency (Phase 1 can be highly parallelized)
            parallel_efficiency = 0.8  # Assume 80% parallel efficiency
            if max_concurrent > 1:
                estimated_parallel_time = estimated_full_scale_time / (max_concurrent * parallel_efficiency)
            else:
                estimated_parallel_time = estimated_full_scale_time
        
        # Final summary
        console.print(f"\n📊 [bold]Phase 1 Summary:[/bold]")
        console.print(f"   ✅ Generated: {projects_generated} project specifications")
        console.print(f"   ⚠️  Skipped: {skipped_projects} specifications (already done)")
        console.print(f"   ❌ Failed: {projects_failed} specifications")
        console.print(f"   📁 Specifications saved to: {generator.generated_dir}")
        
        # ⏰ TIMING SUMMARY
        console.print(f"\n⏰ [bold]Timing Analysis:[/bold]")
        console.print(f"   🕐 Phase duration: {format_duration(phase_duration)}")
        console.print(f"   📅 Started: {phase_start_datetime.strftime('%H:%M:%S')}")
        console.print(f"   📅 Ended: {phase_end_datetime.strftime('%H:%M:%S')}")
        
        if project_times:
            console.print(f"\n📈 [bold]Per-Project Statistics:[/bold]")
            console.print(f"   ⚡ Average: {format_duration(avg_project_time)}")
            console.print(f"   🚀 Fastest: {format_duration(min_project_time)}")
            console.print(f"   🐌 Slowest: {format_duration(max_project_time)}")
            console.print(f"   🔄 Total generation time: {format_duration(total_generation_time)}")
            console.print(f"   🎯 Parallel efficiency: {(total_generation_time/phase_duration)*100:.1f}%")
            
            console.print(f"\n🚀 [bold]Full-Scale Projections ({total_target_projects:,} projects):[/bold]")
            console.print(f"   📊 Sequential: {format_duration(estimated_full_scale_time)}")
            console.print(f"   ⚡ Parallel (x{max_concurrent}): {format_duration(estimated_parallel_time)}")
            
            # Add cost projections if we generated any projects
            if projects_generated > 0:
                            console.print(f"\n💰 [bold]Estimated API Cost Pattern:[/bold]")
            console.print(f"   📝 Per project: ~{avg_project_time:.1f}s average")
            console.print(f"   🔄 Concurrent slots: {max_concurrent}")
            console.print(f"   ⏱️  Expected full run: {format_duration(estimated_parallel_time)}")
            
            # Save timing data for analysis
            timing_stats = {
                'projects_generated': projects_generated,
                'avg_project_time': avg_project_time,
                'min_project_time': min_project_time,
                'max_project_time': max_project_time,
                'total_generation_time': total_generation_time,
                'parallel_efficiency': (total_generation_time/phase_duration)*100,
                'estimated_full_scale_time': estimated_full_scale_time,
                'estimated_parallel_time': estimated_parallel_time,
                'max_concurrent': max_concurrent
            }
            save_timing_summary("1", phase_start_datetime, phase_end_datetime, timing_stats)
        else:
            console.print(f"   ⚠️  No timing data available (no successful generations)")
            save_timing_summary("1", phase_start_datetime, phase_end_datetime, {'projects_generated': 0})
        
        if failed_projects:
            console.print(f"\n⚠️  [yellow]Failed specifications:[/yellow]")
            for failed in failed_projects[:10]:  # Show first 10 failures
                console.print(f"     • {failed}")
            if len(failed_projects) > 10:
                console.print(f"     ... and {len(failed_projects) - 10} more")
                
    except CriticalAuthError as e:
        console.print(f"\n🚨 [bold red]CRITICAL AUTHENTICATION FAILURE[/bold red]")
        console.print(f"🔑 Provider: {e.provider}")
        console.print(f"💬 Error: {e.message}")
        console.print(f"\n📋 Progress saved to: {progress_file}")
        console.print(f"✅ {len(completed_projects)} projects completed before failure")
        console.print(f"\n🔧 [bold yellow]Next steps:[/bold yellow]")
        console.print("   1. Update your API credentials (check api.sh)")
        console.print("   2. Run: source api.sh")
        console.print("   3. Resume with: locobench generate --phase 1")
        console.print("   4. The pipeline will automatically resume from where it stopped")
        
        # Exit with error code
        import sys
        sys.exit(1)


async def run_phase_2_generation(config, force_regenerate=False, max_concurrent=3):
    """Run Phase 2: Synthetic Codebase Generation with parallel processing and resumability"""
    from .generation.synthetic_generator import SyntheticProjectGenerator
    from pathlib import Path
    import json
    import asyncio
    from asyncio import Semaphore
    
    # ⏰ START TIMING
    phase_start_time = time.time()
    phase_start_datetime = datetime.now()
    
    console.print("\n💻 [bold]Synthetic Codebase Generation Pipeline[/bold]")
    console.print("=" * 60)
    console.print(f"⏰ Phase 2 started at: {phase_start_datetime.strftime('%Y-%m-%d %H:%M:%S')}")
    
    # Initialize timing tracking
    project_times = []
    file_counts = []
    line_counts = []
    
    # Setup progress tracking
    progress_file = Path("logs/phase2_progress.json")
    progress_file.parent.mkdir(exist_ok=True)
    completed_projects = load_progress(progress_file)
    completed_project_names = {p.get('project_name', '') for p in completed_projects}
    
    generator = SyntheticProjectGenerator(config, log_file="logs/phase2_generation.log")
    generated_dir = Path(config.data.generated_dir)
    
    # Find all project metadata files from Phase 1
    project_dirs = [d for d in generated_dir.iterdir() if d.is_dir()]
    
    console.print(f"📂 Found {len(project_dirs)} projects from Phase 1")
    console.print(f"📋 Resume state: {len(completed_projects)} projects previously completed")
    
    if force_regenerate:
        console.print("🔄 [yellow]Force mode: Regenerating ALL projects[/yellow]")
        completed_project_names = set()  # Clear resume state
    else:
        console.print("🧠 [cyan]Smart resume: Checking for completed projects...[/cyan]")
    
    if max_concurrent > 1:
        console.print(f"🚀 [bold blue]Parallel mode: {max_concurrent} concurrent projects[/bold blue]")
    
    console.print("🏭 Generating production-quality code with 3 Elite Models...")
    
    # Prepare projects for processing
    projects_to_process = []
    projects_skipped = 0
    
    for project_dir in project_dirs:
        metadata_file = project_dir / "project_metadata.json"
        
        if not metadata_file.exists():
            console.print(f"⚠️  Skipping {project_dir.name} - no metadata found")
            continue
            
        # Load project specification
        with open(metadata_file, 'r') as f:
            project_data = json.load(f)
        
        project_name = f"{project_data['specification']['name']} ({project_data['specification']['language']})"
        
        # Check if project is already completed (unless force regeneration)
        if not force_regenerate and (
            project_name in completed_project_names or 
            'generated_stats' in project_data
        ):
            stats = project_data.get('generated_stats', {})
            # Also verify files actually exist on disk
            expected_files = project_data.get('files', [])
            all_files_exist = all((project_dir / f['path']).exists() for f in expected_files)
            
            if all_files_exist and stats.get('files_count', 0) > 0:
                console.print(f"✅ [green]{project_name} - Already completed![/green]")
                projects_skipped += 1
                continue
        
        projects_to_process.append((project_dir, project_data))
    
    if not projects_to_process:
        console.print("✅ All projects already completed! Use --force to regenerate.")
        return
    
    console.print(f"🎯 Processing {len(projects_to_process)} projects ({projects_skipped} skipped)")
    
    # Semaphore to limit concurrent project generation
    semaphore = Semaphore(max_concurrent)
    
    # Statistics tracking
    total_files_generated = 0
    total_lines_generated = 0
    projects_completed = 0
    
    async def generate_single_project(project_info, project_index):
        """Generate a single project with semaphore control"""
        project_dir, project_data = project_info
        
        async with semaphore:  # Acquire semaphore slot
            spec = project_data['specification']
            project_name = f"{spec['name']} ({spec['language']})"
            
            try:
                console.print(f"🔨 [bold cyan]Starting {project_index}/{len(projects_to_process)}: {project_name}[/bold cyan]")
                
                # Extract target metrics
                target_files = spec.get('target_file_count', 10)
                target_tokens = spec.get('target_token_count', 20000)
                
                console.print(f"   🎯 Target: {target_files} files, ~{target_tokens:,} tokens")
                console.print("   🤖 3 Elite Models working...")
                
                # Start timing
                import time
                start_time = time.time()
                
                # Generate project files
                project_result = await generator.generate_project_files(spec, target_files, target_tokens)
                
                # Extract data from new format
                project_files = project_result['files']
                files_created = project_result['files_created']
                lines_created = project_result['lines_created']
                generation_time = project_result['generation_time']
                
                # Save generated files to project directory
                console.print(f"   💾 Saving {len(project_files)} files...")
                for file_data in project_files:
                    file_path = project_dir / file_data['path']
                    file_path.parent.mkdir(parents=True, exist_ok=True)
                    
                    with open(file_path, 'w', encoding='utf-8') as f:
                        f.write(file_data['content'])
                
                # Update project metadata with generated files
                project_data['files'] = [{'path': f['path'], 'type': f['type']} for f in project_files]
                project_data['generated_stats'] = {
                    'files_count': files_created,
                    'lines_count': lines_created,
                    'generation_time': generation_time,
                    'timestamp': time.time()
                }
                
                # Save updated metadata
                with open(project_dir / "project_metadata.json", 'w') as f:
                    json.dump(project_data, f, indent=2)
                
                console.print(f"   ✅ [green]Completed {project_name}![/green] {files_created} files, {lines_created:,} lines")
                
                # Save progress for successful completion
                import time
                current_progress = {
                    'project_name': project_name,
                    'status': 'completed',
                    'files_created': files_created,
                    'lines_created': lines_created,
                    'timestamp': time.time()
                }
                completed_projects.append(current_progress)
                save_progress(progress_file, completed_projects, "2")
                
                return {
                    'success': True,
                    'files_created': files_created,
                    'lines_created': lines_created,
                    'project_name': project_name,
                    'generation_time': generation_time
                }
                
            except CriticalAuthError as e:
                # Critical auth errors should stop the entire process
                console.print(f"   🚨 [bold red]CRITICAL AUTH FAILURE in {project_name}[/bold red]")
                console.print(f"   🔑 {e.provider}: {e.message}")
                console.print("   🛑 [yellow]Stopping generation to fix authentication...[/yellow]")
                
                # Save current progress before stopping
                current_progress = {
                    'project_name': project_name,
                    'status': 'auth_failed',
                    'error': str(e),
                    'timestamp': time.time()
                }
                completed_projects.append(current_progress)
                save_progress(progress_file, completed_projects, "2")
                
                # Re-raise to stop the entire process
                raise e
                
            except Exception as e:
                console.print(f"   ❌ [red]Failed {project_name}: {str(e)}[/red]")
                return {
                    'success': False,
                    'error': str(e),
                    'project_name': project_name
                }
    
    # Execute all projects in parallel with progress tracking
    console.print(f"\n🚀 [bold]Starting parallel generation of {len(projects_to_process)} projects...[/bold]")
    
    try:
        # Create tasks for all projects
        tasks = []
        for i, project_info in enumerate(projects_to_process, 1):
            task = generate_single_project(project_info, i)
            tasks.append(task)
        
        # Wait for all projects to complete
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Check for CriticalAuthError in results
        for result in results:
            if isinstance(result, CriticalAuthError):
                raise result
        
        # Process results
        successful_projects = []
        failed_projects = []
        
        for result in results:
            if isinstance(result, Exception):
                failed_projects.append(f"Exception: {str(result)}")
            elif result and result['success']:
                successful_projects.append(result)
                total_files_generated += result['files_created']
                total_lines_generated += result['lines_created']
                projects_completed += 1
                # Collect timing data if available
                if 'generation_time' in result:
                    project_times.append(result['generation_time'])
                if 'files_created' in result:
                    file_counts.append(result['files_created'])
                if 'lines_created' in result:
                    line_counts.append(result['lines_created'])
            else:
                failed_projects.append(result['project_name'] if result else "Unknown project")
        
        # ⏰ TIMING ANALYSIS
        phase_end_time = time.time()
        phase_duration = phase_end_time - phase_start_time
        phase_end_datetime = datetime.now()
        
        # Convert to human readable
        def format_duration(seconds):
            if seconds < 60:
                return f"{seconds:.1f}s"
            elif seconds < 3600:
                return f"{seconds/60:.1f}m"
            else:
                return f"{seconds/3600:.1f}h"
        
        # Calculate timing statistics
        if project_times:
            avg_project_time = sum(project_times) / len(project_times)
            min_project_time = min(project_times)
            max_project_time = max(project_times)
            total_generation_time = sum(project_times)
            
            # Calculate throughput metrics
            avg_files_per_project = sum(file_counts) / len(file_counts) if file_counts else 0
            avg_lines_per_project = sum(line_counts) / len(line_counts) if line_counts else 0
            files_per_minute = (total_files_generated / phase_duration) * 60 if phase_duration > 0 else 0
            lines_per_minute = (total_lines_generated / phase_duration) * 60 if phase_duration > 0 else 0
            
            # Calculate full-scale projections for Phase 2
            total_target_projects = len(config.phase1.supported_languages) * config.phase1.projects_per_language
            estimated_full_scale_time = avg_project_time * total_target_projects
            
            # Phase 2 has lower parallel efficiency due to file generation complexity
            parallel_efficiency = 0.6  # Assume 60% parallel efficiency for file generation
            if max_concurrent > 1:
                estimated_parallel_time = estimated_full_scale_time / (max_concurrent * parallel_efficiency)
            else:
                estimated_parallel_time = estimated_full_scale_time
        
        # Final summary
        console.print(f"\n📊 [bold]Phase 2 Summary:[/bold]")
        console.print(f"   ✅ Completed: {projects_completed} projects")
        console.print(f"   ⚠️  Skipped: {projects_skipped} projects (already done)")
        console.print(f"   ❌ Failed: {len(failed_projects)} projects")
        console.print(f"   📄 Total files generated: {total_files_generated:,}")
        console.print(f"   📝 Total lines generated: {total_lines_generated:,}")
        
        # ⏰ TIMING SUMMARY
        console.print(f"\n⏰ [bold]Timing Analysis:[/bold]")
        console.print(f"   🕐 Phase duration: {format_duration(phase_duration)}")
        console.print(f"   📅 Started: {phase_start_datetime.strftime('%H:%M:%S')}")
        console.print(f"   📅 Ended: {phase_end_datetime.strftime('%H:%M:%S')}")
        
        if project_times:
            console.print(f"\n📈 [bold]Per-Project Statistics:[/bold]")
            console.print(f"   ⚡ Average time: {format_duration(avg_project_time)}")
            console.print(f"   🚀 Fastest: {format_duration(min_project_time)}")
            console.print(f"   🐌 Slowest: {format_duration(max_project_time)}")
            console.print(f"   📄 Avg files/project: {avg_files_per_project:.1f}")
            console.print(f"   📝 Avg lines/project: {avg_lines_per_project:.0f}")
            console.print(f"   🎯 Parallel efficiency: {(total_generation_time/phase_duration)*100:.1f}%")
            
            console.print(f"\n🏭 [bold]Throughput Metrics:[/bold]")
            console.print(f"   📄 Files/minute: {files_per_minute:.1f}")
            console.print(f"   📝 Lines/minute: {lines_per_minute:.0f}")
            console.print(f"   🔄 Total generation time: {format_duration(total_generation_time)}")
            
            console.print(f"\n🚀 [bold]Full-Scale Projections ({total_target_projects:,} projects):[/bold]")
            console.print(f"   📊 Sequential: {format_duration(estimated_full_scale_time)}")
            console.print(f"   ⚡ Parallel (x{max_concurrent}): {format_duration(estimated_parallel_time)}")
            console.print(f"   📄 Expected files: {int(avg_files_per_project * total_target_projects):,}")
            console.print(f"   📝 Expected lines: {int(avg_lines_per_project * total_target_projects):,}")
            
            # Save timing data for analysis
            timing_stats = {
                'projects_completed': projects_completed,
                'total_files_generated': total_files_generated,
                'total_lines_generated': total_lines_generated,
                'avg_project_time': avg_project_time,
                'min_project_time': min_project_time,
                'max_project_time': max_project_time,
                'avg_files_per_project': avg_files_per_project,
                'avg_lines_per_project': avg_lines_per_project,
                'files_per_minute': files_per_minute,
                'lines_per_minute': lines_per_minute,
                'parallel_efficiency': (total_generation_time/phase_duration)*100,
                'estimated_full_scale_time': estimated_full_scale_time,
                'estimated_parallel_time': estimated_parallel_time,
                'max_concurrent': max_concurrent
            }
            save_timing_summary("2", phase_start_datetime, phase_end_datetime, timing_stats)
        else:
            console.print(f"   ⚠️  No timing data available (no successful generations)")
            save_timing_summary("2", phase_start_datetime, phase_end_datetime, {'projects_completed': 0})
        
        if failed_projects:
            console.print(f"\n⚠️  [yellow]Failed projects:[/yellow]")
            for failed in failed_projects[:10]:  # Show first 10
                console.print(f"     • {failed}")
            if len(failed_projects) > 10:
                console.print(f"     ... and {len(failed_projects) - 10} more")
                
    except CriticalAuthError as e:
        console.print(f"\n🚨 [bold red]CRITICAL AUTHENTICATION FAILURE[/bold red]")
        console.print(f"🔑 Provider: {e.provider}")
        console.print(f"💬 Error: {e.message}")
        console.print(f"\n📋 Progress saved to: {progress_file}")
        console.print(f"✅ {len(completed_projects)} projects completed before failure")
        console.print(f"\n🔧 [bold yellow]Next steps:[/bold yellow]")
        console.print("   1. Update your API credentials (check api.sh)")
        console.print("   2. Run: source api.sh")
        console.print("   3. Resume with: locobench generate --phase 2")
        console.print("   4. The pipeline will automatically resume from where it stopped")
        
        # Exit with error code
        import sys
        sys.exit(1)


async def run_phase_3_generation(config, force_regenerate=False, max_concurrent=3):
    """Run Phase 3: Long-Context Evaluation Scenario Creation with parallel processing, progress tracking, and resumability"""
    from .generation.scenario_generator import ScenarioGenerator
    from .core.task import TaskCategory
    from pathlib import Path
    import json
    import asyncio
    from asyncio import Semaphore
    
    # ⏰ START TIMING
    phase_start_time = time.time()
    phase_start_datetime = datetime.now()
    
    console.print("\n🎮 [bold]Long-Context Evaluation Scenario Creation Pipeline[/bold]")
    console.print("=" * 60)
    console.print(f"⏰ Phase 3 started at: {phase_start_datetime.strftime('%Y-%m-%d %H:%M:%S')}")
    
    # Setup progress tracking
    progress_file = Path("logs/phase3_progress.json")
    progress_file.parent.mkdir(exist_ok=True)
    completed_scenarios = load_progress(progress_file)
    completed_scenario_keys = {f"{s.get('project_name', '')}_{s.get('category', '')}" for s in completed_scenarios}
    
    generator = ScenarioGenerator(config, log_file="logs/phase3_generation.log")
    generated_dir = Path(config.data.generated_dir)
    scenarios_dir = Path(config.data.output_dir) / "scenarios"
    scenarios_dir.mkdir(parents=True, exist_ok=True)
    
    console.print(f"📋 Resume state: {len(completed_scenarios)} scenario tasks previously completed")
    
    # Find all completed projects from Phase 2
    project_dirs = [d for d in generated_dir.iterdir() if d.is_dir()]
    completed_projects = []
    
    for project_dir in project_dirs:
        metadata_file = project_dir / "project_metadata.json"
        if metadata_file.exists():
            with open(metadata_file, 'r') as f:
                project_data = json.load(f)
            # Check if project has generated code files
            if 'generated_stats' in project_data and project_data['generated_stats'].get('files_count', 0) > 0:
                completed_projects.append((project_dir, project_data))
    
    console.print(f"📂 Found {len(completed_projects)} completed projects from Phase 2")
    
    if len(completed_projects) == 0:
        console.print("⚠️  [yellow]No completed projects found. Run Phase 2 first![/yellow]")
        return
    
    if force_regenerate:
        console.print("🔄 [yellow]Force mode: Regenerating ALL scenarios[/yellow]")
    else:
        console.print("🧠 [cyan]Smart resume: Checking for completed scenarios...[/cyan]")
    
    if max_concurrent > 1:
        console.print(f"🚀 [bold blue]Parallel mode: {max_concurrent} concurrent scenario generations[/bold blue]")
    
    console.print("🎯 Creating evaluation scenarios with 2 Elite Models...")
    
    # Calculate scenario distribution based on config task_distribution
    task_categories = list(TaskCategory)
    
    # Validate that all configured task categories exist in our enum
    config_categories = set(config.phase3.task_distribution.keys())
    enum_categories = {cat.value for cat in task_categories}
    missing_categories = config_categories - enum_categories
    if missing_categories:
        console.print(f"⚠️  [yellow]Warning: Config contains unknown task categories: {missing_categories}[/yellow]")
    
    # Create distribution map from config
    task_instance_counts = {}
    total_projects_all_languages = len(completed_projects)
    
    for task_category in task_categories:
        if task_category.value in config.phase3.task_distribution:
            # Use configured count
            target_count = config.phase3.task_distribution[task_category.value]
            instances_per_project = max(1, target_count // total_projects_all_languages)
            task_instance_counts[task_category] = instances_per_project
        else:
            # Fallback for missing categories
            console.print(f"⚠️  [yellow]Warning: {task_category.value} not in config task_distribution, using default[/yellow]")
            task_instance_counts[task_category] = 2
    
    # Prepare scenario generation tasks - DISTRIBUTION-ENFORCED GENERATION
    console.print(f"📋 Target Difficulty Distribution (ENFORCED):")
    target_distribution = {}
    for difficulty, count in config.phase3.difficulty_distribution.items():
        target_distribution[difficulty] = count
        console.print(f"  • {difficulty}: {count} scenarios")
    
    console.print(f"📋 Task Distribution (from config):")
    for task_category, instances_per_project in task_instance_counts.items():
        total_for_category = instances_per_project * total_projects_all_languages
        console.print(f"  • {task_category.value}: {instances_per_project} per project × {total_projects_all_languages} projects = {total_for_category} total")
    
    # Track current difficulty distribution
    current_distribution = {"easy": 0, "medium": 0, "hard": 0, "expert": 0}
    
    # Create difficulty assignment strategy
    def get_next_target_difficulty():
        """Determine which difficulty level we need more of to achieve target distribution"""
        for difficulty in ["expert", "hard", "medium", "easy"]:  # Prioritize harder difficulties
            target_count = target_distribution.get(difficulty, 0)
            current_count = current_distribution.get(difficulty, 0)
            if current_count < target_count:
                return difficulty
        # If we've met all targets, cycle through difficulties
        return random.choice(["easy", "medium", "hard", "expert"])
    
    scenario_tasks = []
    scenarios_skipped = 0
    total_scenarios_planned = sum(task_instance_counts.values()) * total_projects_all_languages
    
    console.print(f"\n🎯 [bold]Distribution-Enforced Generation: {total_scenarios_planned} scenarios[/bold]")
    console.print("🔧 [cyan]Each scenario will target a specific difficulty to achieve desired distribution[/cyan]")
    
    for project_dir, project_data in completed_projects:
        for task_category in task_categories:
            # Generate the configured number of scenarios for this combination
            instances_for_category = task_instance_counts[task_category]
            
            for instance_num in range(instances_for_category):
                # Determine target difficulty for this scenario
                target_difficulty_name = get_next_target_difficulty()
                current_distribution[target_difficulty_name] += 1  # Reserve this slot
                
                # Generate unique scenario file name with target difficulty
                scenario_file = scenarios_dir / f"{project_dir.name}_{task_category.value}_{target_difficulty_name}_{instance_num+1:02d}.json"
                
                if not force_regenerate and scenario_file.exists():
                    console.print(f"✅ [green]{scenario_file.name} already exists[/green]")
                    scenarios_skipped += 1
                    continue
                
                scenario_tasks.append({
                    'project_dir': project_dir,
                    'project_data': project_data,
                    'task_category': task_category,
                    'target_difficulty': target_difficulty_name,  # NEW: Target specific difficulty
                    'instance_num': instance_num + 1,
                    'scenario_file': scenario_file,
                    'scenario_id': f"{project_dir.name}_{task_category.value}_{target_difficulty_name}_{instance_num+1:02d}"
                })
    
    console.print(f"\n🎯 [bold]Total scenarios planned: {total_scenarios_planned}[/bold]")
    
    if not scenario_tasks:
        console.print("✅ All scenarios already completed! Use --force to regenerate.")
        return
    
    console.print(f"🎯 Processing {len(scenario_tasks)} scenario generation tasks ({scenarios_skipped} skipped)")
    
    # Semaphore to limit concurrent scenario generation
    semaphore = Semaphore(max_concurrent)
    
    # Statistics tracking
    total_scenarios_generated = 0
    tasks_completed = 0
    
    async def generate_single_scenario_task(task_info, task_index):
        """Generate a single scenario (individual scenario-level parallelization)"""
        async with semaphore:  # Acquire semaphore slot
            project_dir = task_info['project_dir']
            project_data = task_info['project_data']
            task_category = task_info['task_category']
            target_difficulty_name = task_info['target_difficulty']
            scenario_file = task_info['scenario_file']
            scenario_id = task_info['scenario_id']
            
            # Convert target difficulty string to enum
            difficulty_map = {
                "easy": DifficultyLevel.EASY,
                "medium": DifficultyLevel.MEDIUM,
                "hard": DifficultyLevel.HARD,
                "expert": DifficultyLevel.EXPERT
            }
            target_difficulty = difficulty_map[target_difficulty_name]
            
            project_name = project_data['specification']['name']
            category_name = task_category.value
            
            # Skip if already completed (resume functionality)
            if not force_regenerate and scenario_file.exists():
                console.print(f"✅ [green]Skipping {scenario_file.name} - Already completed![/green]")
                return {
                    'success': True,
                    'skipped': True,
                    'project_name': project_name,
                    'category': category_name,
                    'target_difficulty': target_difficulty_name
                }
            
            try:
                console.print(f"🔨 [bold cyan]Starting {task_index}/{len(scenario_tasks)}: {project_name} - {category_name} ({target_difficulty_name.upper()})[/bold cyan]")
                
                # Start timing
                import time
                start_time = time.time()
                
                # Generate single scenario directly using the low-level method
                project_files = generator._load_project_files(project_dir, project_data)
                scenario = await generator._generate_single_scenario(
                    scenario_id=scenario_id,
                    task_category=task_category,
                    project_spec=project_data['specification'],
                    project_files=project_files,
                    project_stats=project_data['generated_stats'],
                    target_difficulty=target_difficulty
                )
                
                generation_time = time.time() - start_time
                
                # Safety check: Ensure we actually generated a scenario
                if not scenario:
                    error_msg = f"No scenario generated for {scenario_id}"
                    console.print(f"   ❌ [red]{error_msg}[/red]")
                    return {
                        'success': False,
                        'error': error_msg,
                        'project_name': project_name,
                        'category': category_name,
                        'target_difficulty': target_difficulty_name
                    }
                
                # Save scenario to individual file (one scenario per file)
                with open(scenario_file, 'w') as f:
                    json.dump(scenario, f, indent=2)
                
                console.print(f"   ✅ [green]Completed {project_name} - {category_name} ({target_difficulty_name.upper()})![/green] 1 scenario in {generation_time:.1f}s")
                
                # Save progress for successful completion
                current_progress = {
                    'project_name': project_name,
                    'category': category_name,
                    'status': 'completed',
                    'scenarios_generated': 1,
                    'generation_time': generation_time,
                    'timestamp': time.time()
                }
                completed_scenarios.append(current_progress)
                save_progress(progress_file, completed_scenarios, "3")
                
                return {
                    'success': True,
                    'scenarios_generated': 1,
                    'project_name': project_name,
                    'category': category_name,
                    'generation_time': generation_time,
                    'target_difficulty': target_difficulty_name
                }
                
            except CriticalAuthError as e:
                # Critical auth errors should stop the entire process
                console.print(f"   🚨 [bold red]CRITICAL AUTH FAILURE in {project_name} - {category_name}[/bold red]")
                console.print(f"   🔑 {e.provider}: {e.message}")
                console.print("   🛑 [yellow]Stopping generation to fix authentication...[/yellow]")
                
                # Save current progress before stopping
                current_progress = {
                    'project_name': project_name,
                    'category': category_name,
                    'status': 'auth_failed',
                    'error': str(e),
                    'timestamp': time.time()
                }
                completed_scenarios.append(current_progress)
                save_progress(progress_file, completed_scenarios, "3")
                
                # Re-raise to stop the entire process
                raise e
                
            except Exception as e:
                error_str = str(e)
                console.print(f"   ❌ [red]Failed {project_name} - {category_name} ({target_difficulty_name.upper()}): {error_str}[/red]")
                
                return {
                    'success': False,
                    'error': error_str,
                    'project_name': project_name,
                    'category': category_name,
                    'target_difficulty': target_difficulty_name
                }
    
    # Execute all scenario generation tasks in parallel
    console.print(f"\n🚀 [bold]Starting parallel scenario generation for {len(scenario_tasks)} individual scenarios...[/bold]")
    
    try:
        # Create asyncio tasks for individual scenarios (not project+category groups)
        tasks = []
        for i, task_info in enumerate(scenario_tasks, 1):
            task = generate_single_scenario_task(task_info, i)
            tasks.append(task)
        
        # Wait for all tasks to complete
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Check for CriticalAuthError in results
        for result in results:
            if isinstance(result, CriticalAuthError):
                raise result
        
        # Process results
        successful_tasks = []
        failed_tasks = []
        skipped_tasks = 0
        
        for result in results:
            if isinstance(result, Exception):
                failed_tasks.append(f"Exception: {str(result)}")
            elif result and result['success']:
                if result.get('skipped'):
                    skipped_tasks += 1
                else:
                    successful_tasks.append(result)
                    total_scenarios_generated += result['scenarios_generated']
                    tasks_completed += 1
            else:
                failed_tasks.append(f"{result['project_name']} - {result['category']}" if result else "Unknown task")
        
        # ⏰ TIMING ANALYSIS
        phase_end_time = time.time()
        phase_duration = phase_end_time - phase_start_time
        phase_end_datetime = datetime.now()
        
        # Convert to human readable
        def format_duration(seconds):
            if seconds < 60:
                return f"{seconds:.1f}s"
            elif seconds < 3600:
                return f"{seconds/60:.1f}m"
            else:
                return f"{seconds/3600:.1f}h"
        
        # Final summary
        console.print(f"\n📊 [bold]Phase 3 Summary:[/bold]")
        console.print(f"   ✅ Completed: {tasks_completed} scenario generation tasks")
        console.print(f"   ⚠️  Skipped: {skipped_tasks + scenarios_skipped} tasks (already done)")
        console.print(f"   ❌ Failed: {len(failed_tasks)} tasks")
        console.print(f"   🎯 Total scenarios generated: {total_scenarios_generated}")
        console.print(f"   📁 Scenarios saved to: {scenarios_dir}")
        
        # 📊 DIFFICULTY DISTRIBUTION ANALYSIS
        console.print(f"\n📊 [bold]Difficulty Distribution Analysis:[/bold]")
        console.print("🔬 [cyan]Analyzing actual vs desired difficulty distribution...[/cyan]")
        
        # Analyze generated scenarios to see actual difficulty distribution
        actual_distribution = {"easy": 0, "medium": 0, "hard": 0, "expert": 0}
        total_analyzed = 0
        
        for scenario_file in scenarios_dir.glob("*.json"):
            try:
                with open(scenario_file, 'r') as f:
                    scenario_data = json.load(f)
                # Each file contains a single scenario object, not an array
                difficulty = scenario_data.get('difficulty', '').lower()
                if difficulty in actual_distribution:
                    actual_distribution[difficulty] += 1
                    total_analyzed += 1
            except Exception as e:
                logger.debug(f"Error analyzing {scenario_file}: {e}")
        
        console.print(f"   📈 Analyzed {total_analyzed} scenarios from {len(list(scenarios_dir.glob('*.json')))} files")
        console.print(f"\n   📋 Distribution Comparison:")
        console.print(f"   {'Difficulty':<12} {'Desired':<8} {'Actual':<8} {'Diff':<8} {'%':<8}")
        console.print(f"   {'-'*50}")
        
        for difficulty in ["easy", "medium", "hard", "expert"]:
            desired = target_distribution.get(difficulty, 0)
            actual = actual_distribution.get(difficulty, 0)
            diff = actual - desired
            percentage = (actual / desired * 100) if desired > 0 else 0
            
            # Color coding for the difference
            diff_color = "green" if abs(diff) <= 2 else "yellow" if abs(diff) <= 5 else "red"
            console.print(f"   {difficulty:<12} {desired:<8} {actual:<8} [bold {diff_color}]{diff:+3d}[/bold {diff_color}]     {percentage:5.1f}%")
        
        # Overall assessment
        total_desired = sum(target_distribution.values())
        deviation_score = sum(abs(actual_distribution[d] - target_distribution.get(d, 0)) for d in actual_distribution.keys())
        
        if deviation_score <= total_desired * 0.1:  # Within 10%
            console.print(f"   🎯 [bold green]Excellent distribution match![/bold green] (deviation: {deviation_score})")
        elif deviation_score <= total_desired * 0.2:  # Within 20%
            console.print(f"   ✅ [bold yellow]Good distribution match[/bold yellow] (deviation: {deviation_score})")
        else:
            console.print(f"   ⚠️  [bold red]Distribution needs improvement[/bold red] (deviation: {deviation_score})")
            console.print(f"   💡 [cyan]Tip: Adjust file selection or context length ranges to improve distribution[/cyan]")
        
        # ⏰ TIMING SUMMARY
        console.print(f"\n⏰ [bold]Timing Analysis:[/bold]")
        console.print(f"   🕐 Phase duration: {format_duration(phase_duration)}")
        console.print(f"   📅 Started: {phase_start_datetime.strftime('%H:%M:%S')}")
        console.print(f"   📅 Ended: {phase_end_datetime.strftime('%H:%M:%S')}")
        
        if tasks_completed > 0:
            avg_task_time = phase_duration / (tasks_completed + len(failed_tasks)) if (tasks_completed + len(failed_tasks)) > 0 else 0
            console.print(f"   ⚡ Average task time: {format_duration(avg_task_time)}")
            if total_scenarios_generated > 0:
                scenarios_per_minute = (total_scenarios_generated / phase_duration) * 60 if phase_duration > 0 else 0
                console.print(f"   🎯 Scenarios/minute: {scenarios_per_minute:.1f}")
        else:
            console.print(f"   ⚠️  No timing data available (no successful completions)")
        
        if failed_tasks:
            console.print(f"\n⚠️  [yellow]Failed tasks:[/yellow]")
            for failed in failed_tasks[:10]:  # Show first 10 failures
                console.print(f"     • {failed}")
            if len(failed_tasks) > 10:
                console.print(f"     ... and {len(failed_tasks) - 10} more")
                
    except CriticalAuthError as e:
        console.print(f"\n🚨 [bold red]CRITICAL AUTHENTICATION FAILURE[/bold red]")
        console.print(f"🔑 Provider: {e.provider}")
        console.print(f"💬 Error: {e.message}")
        console.print(f"\n📋 Progress saved to: {progress_file}")
        console.print(f"✅ {len(completed_scenarios)} scenario tasks completed before failure")
        console.print(f"\n🔧 [bold yellow]Next steps:[/bold yellow]")
        console.print("   1. Update your API credentials (check api.sh)")
        console.print("   2. Run: source api.sh")
        console.print("   3. Resume with: locobench generate --phase 3")
        console.print("   4. The pipeline will automatically resume from where it stopped")
        
        # Exit with error code
        import sys
        sys.exit(1)


async def run_phase_4_generation(config, force_regenerate=False, max_concurrent=3):
    """Run Phase 4: Automated Test-Driven Validation Framework with parallel processing, progress tracking, and resumability"""
    from .generation.validation_framework import AutomatedValidator
    from .core.task import TaskCategory
    from pathlib import Path
    import json
    import asyncio
    from asyncio import Semaphore
    
    # ⏰ START TIMING
    phase_start_time = time.time()
    phase_start_datetime = datetime.now()
    
    console.print("\n🧪 [bold]Automated Test-Driven Validation Framework[/bold]")
    console.print("=" * 60)
    console.print(f"⏰ Phase 4 started at: {phase_start_datetime.strftime('%Y-%m-%d %H:%M:%S')}")
    
    # Setup progress tracking
    progress_file = Path("logs/phase4_progress.json")
    progress_file.parent.mkdir(exist_ok=True)
    completed_validations = load_progress(progress_file)
    completed_scenario_files = {v.get('scenario_file', '') for v in completed_validations}
    
    validator = AutomatedValidator(config)
    scenarios_dir = Path(config.data.output_dir) / "scenarios"
    
    console.print(f"📋 Resume state: {len(completed_validations)} validation tasks previously completed")
    
    if not scenarios_dir.exists():
        console.print("⚠️  [yellow]No scenarios found. Run Phase 3 first![/yellow]")
        return
    
    # Find all scenario files
    scenario_files = list(scenarios_dir.glob("*.json"))
    
    if len(scenario_files) == 0:
        console.print("⚠️  [yellow]No scenario files found. Run Phase 3 first![/yellow]")
        return
    
    console.print(f"📂 Found {len(scenario_files)} scenario files from Phase 3")
    
    if force_regenerate:
        console.print("🔄 [yellow]Force mode: Regenerating ALL test suites[/yellow]")
    else:
        console.print("🧠 [cyan]Smart resume: Checking for completed test suites...[/cyan]")
    
    if max_concurrent > 1:
        console.print(f"🚀 [bold blue]Parallel mode: {max_concurrent} concurrent test suite generations[/bold blue]")
    
    console.print("🎯 Creating automated test suites for evaluation...")
    console.print(f"⚖️  Evaluation weights: Software Engineering (40%) | Functional Correctness (30%) | Code Quality (20%) | Long-Context Util (10%)")
    
    # Prepare test suite generation tasks
    validation_tasks = []
    test_suites_skipped = 0
    
    for scenario_file in scenario_files:
        # Check if test suite already exists
        validation_dir = Path(config.data.output_dir) / "validation" / "test_suites"
        validation_dir.mkdir(parents=True, exist_ok=True)
        
        test_suite_file = validation_dir / f"{scenario_file.stem}_test_suite.json"
        
        if not force_regenerate and test_suite_file.exists():
            console.print(f"✅ [green]{scenario_file.name} - test suite already exists[/green]")
            test_suites_skipped += 1
            continue
        
        validation_tasks.append({
            'scenario_file': scenario_file,
            'test_suite_file': test_suite_file
        })
    
    if not validation_tasks:
        console.print("✅ All test suites already completed! Use --force to regenerate.")
        return
    
    console.print(f"🎯 Processing {len(validation_tasks)} test suite generation tasks ({test_suites_skipped} skipped)")
    
    # Semaphore to limit concurrent test suite generation
    semaphore = Semaphore(max_concurrent)
    
    # Statistics tracking
    total_test_suites_generated = 0
    tasks_completed = 0
    
    async def generate_test_suite_for_scenarios(task_info, task_index):
        """Generate test suite for one scenario file"""
        async with semaphore:  # Acquire semaphore slot
            scenario_file = task_info['scenario_file']
            test_suite_file = task_info['test_suite_file']
            
            # Skip if already completed (resume functionality)
            if not force_regenerate and scenario_file.name in completed_scenario_files:
                console.print(f"✅ [green]Skipping {scenario_file.name} - Already completed![/green]")
                return {
                    'success': True,
                    'skipped': True,
                    'scenario_file': scenario_file.name
                }
            
            try:
                console.print(f"🔨 [bold cyan]Starting {task_index}/{len(validation_tasks)}: {scenario_file.name}[/bold cyan]")
                
                # Load scenarios
                with open(scenario_file, 'r') as f:
                    scenario_data = json.load(f)
                
                scenarios = scenario_data.get('scenarios', [])
                if not scenarios:
                    console.print(f"   ⚠️  [yellow]No scenarios found in {scenario_file.name}[/yellow]")
                    return {'success': True, 'test_suites_generated': 0, 'scenario_file': scenario_file.name}
                
                # Start timing
                import time
                start_time = time.time()
                
                # Generate test suites for all scenarios in this file
                test_suites = []
                for scenario in scenarios:
                    test_suite = await validator.generate_test_suite(scenario)
                    test_suites.append({
                        'scenario_id': scenario.get('id', 'unknown'),
                        'test_suite': test_suite.to_dict()  # Convert to dict for JSON serialization
                    })
                
                generation_time = time.time() - start_time
                
                # Save test suites
                test_suite_data = {
                    'source_file': scenario_file.name,
                    'generated_timestamp': time.time(),
                    'generation_time': generation_time,
                    'test_suites': test_suites
                }
                
                with open(test_suite_file, 'w') as f:
                    json.dump(test_suite_data, f, indent=2)
                
                console.print(f"   ✅ [green]Completed {scenario_file.name}![/green] {len(test_suites)} test suites in {generation_time:.1f}s")
                
                # Save progress for successful completion
                current_progress = {
                    'scenario_file': scenario_file.name,
                    'status': 'completed',
                    'test_suites_generated': len(test_suites),
                    'generation_time': generation_time,
                    'timestamp': time.time()
                }
                completed_validations.append(current_progress)
                save_progress(progress_file, completed_validations, "4")
                
                return {
                    'success': True,
                    'test_suites_generated': len(test_suites),
                    'scenario_file': scenario_file.name,
                    'generation_time': generation_time
                }
                
            except Exception as e:
                console.print(f"   ❌ [red]Failed {scenario_file.name}: {str(e)}[/red]")
                return {
                    'success': False,
                    'error': str(e),
                    'scenario_file': scenario_file.name
                }
    
    # Execute all test suite generation tasks in parallel
    console.print(f"\n🚀 [bold]Starting parallel test suite generation for {len(validation_tasks)} tasks...[/bold]")
    
    try:
        # Create asyncio tasks
        tasks = []
        for i, task_info in enumerate(validation_tasks, 1):
            task = generate_test_suite_for_scenarios(task_info, i)
            tasks.append(task)
        
        # Wait for all tasks to complete
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Process results
        successful_tasks = []
        failed_tasks = []
        skipped_tasks = 0
        
        for result in results:
            if isinstance(result, Exception):
                failed_tasks.append(f"Exception: {str(result)}")
            elif result and result['success']:
                if result.get('skipped'):
                    skipped_tasks += 1
                else:
                    successful_tasks.append(result)
                    total_test_suites_generated += result['test_suites_generated']
                    tasks_completed += 1
            else:
                failed_tasks.append(result['scenario_file'] if result else "Unknown task")
        
        # ⏰ TIMING ANALYSIS
        phase_end_time = time.time()
        phase_duration = phase_end_time - phase_start_time
        phase_end_datetime = datetime.now()
        
        # Convert to human readable
        def format_duration(seconds):
            if seconds < 60:
                return f"{seconds:.1f}s"
            elif seconds < 3600:
                return f"{seconds/60:.1f}m"
            else:
                return f"{seconds/3600:.1f}h"
        
        # Final summary
        console.print(f"\n📊 [bold]Phase 4 Summary:[/bold]")
        console.print(f"   ✅ Completed: {tasks_completed} test suite generation tasks")
        console.print(f"   ⚠️  Skipped: {skipped_tasks + test_suites_skipped} tasks (already done)")
        console.print(f"   ❌ Failed: {len(failed_tasks)} tasks")
        console.print(f"   🧪 Total test suites generated: {total_test_suites_generated}")
        console.print(f"   📁 Test suites saved to: {Path(config.data.output_dir) / 'validation' / 'test_suites'}")
        
        # ⏰ TIMING SUMMARY
        console.print(f"\n⏰ [bold]Timing Analysis:[/bold]")
        console.print(f"   🕐 Phase duration: {format_duration(phase_duration)}")
        console.print(f"   📅 Started: {phase_start_datetime.strftime('%H:%M:%S')}")
        console.print(f"   📅 Ended: {phase_end_datetime.strftime('%H:%M:%S')}")
        
        if tasks_completed > 0:
            avg_task_time = phase_duration / (tasks_completed + len(failed_tasks)) if (tasks_completed + len(failed_tasks)) > 0 else 0
            console.print(f"   ⚡ Average task time: {format_duration(avg_task_time)}")
            if total_test_suites_generated > 0:
                test_suites_per_minute = (total_test_suites_generated / phase_duration) * 60 if phase_duration > 0 else 0
                console.print(f"   🧪 Test suites/minute: {test_suites_per_minute:.1f}")
        else:
            console.print(f"   ⚠️  No timing data available (no successful completions)")
        
        if failed_tasks:
            console.print(f"\n⚠️  [yellow]Failed tasks:[/yellow]")
            for failed in failed_tasks[:10]:  # Show first 10 failures
                console.print(f"     • {failed}")
            if len(failed_tasks) > 10:
                console.print(f"     ... and {len(failed_tasks) - 10} more")
                
    except Exception as e:
        console.print(f"\n❌ [bold red]EXECUTION FAILURE[/bold red]")
        console.print(f"💬 Error: {str(e)}")
        console.print(f"\n📋 Progress saved to: {progress_file}")
        console.print(f"✅ {len(completed_validations)} validation tasks completed before failure")
        console.print(f"\n🔧 [bold yellow]Next steps:[/bold yellow]")
        console.print("   1. Check the error details above")
        console.print("   2. Resume with: locobench generate --phase 4")
        console.print("   3. The pipeline will automatically resume from where it stopped")
        
        # Exit with error code
        import sys
        sys.exit(1)


if __name__ == '__main__':
    main() 