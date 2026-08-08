import argparse

def run_enrich(args: argparse.Namespace) -> str:
    from semapact.tools.enricher import ContractEnricher

    print("🤖 Starting LLM Enrichment... (Note: Existing human-annotated fields will not be overwritten)")
    enricher = ContractEnricher()
    enricher.process(
        args.contract,
        max_workers=getattr(args, "concurrency", 1),
        mode=getattr(args, "mode", "label"),
        system_prompt=getattr(args, "system_prompt", None),
        user_prompt=getattr(args, "user_prompt", None),
    )
    return f"Successfully enriched {args.contract} (mode: {getattr(args, 'mode', 'label')})"
