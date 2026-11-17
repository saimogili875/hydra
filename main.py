"""
Main Pipeline Runner for HMDA Lake Register to FTL Polygons.
Usage:
    python3 main.py --stage 1    # Run Stage 1 (PDF parsing & Excel initialization)
    python3 main.py --stage 2    # Run Stage 2 (Map download test with 5 lakes)
    python3 main.py --stage 3    # Run Stage 3 (Satellite Map, Verification & Interactive View)
    python3 main.py --all        # Run all stages sequentially
"""

import argparse
import sys
import os


def run_stage_1():
    print("=" * 60)
    print("Stage 1: Reading HMDA Lakes Register PDF & initializing Excel...")
    print("=" * 60)
    raise NotImplementedError("Stage 1 (Register PDF parsing) is not implemented yet.")


def run_stage_2():
    print("=" * 60)
    print("Stage 2: Map download test...")
    print("=" * 60)
    raise NotImplementedError("Stage 2 (Bulk map download) is not implemented yet.")


def run_stage_3(lake_id=None, all_lakes=False):
    print("=" * 60)
    print("Stage 3: Generating Satellite Map, Verification & Interactive View...")
    print("=" * 60)
    from src.mapview import run_pipeline
    return run_pipeline(lake_id=lake_id, all_lakes=all_lakes)


def main():
    parser = argparse.ArgumentParser(description="HMDA Lake Register Pipeline")
    parser.add_argument("--stage", type=int, choices=[1, 2, 3, 4, 5], help="Run a specific stage")
    parser.add_argument("--lake", type=str, help="Process a specific lake ID (e.g. 871)")
    parser.add_argument("--all", action="store_true", help="Process all lakes")
    args = parser.parse_args()

    if args.stage == 1:
        run_stage_1()
    elif args.stage == 2:
        run_stage_2()
    elif args.stage == 3:
        run_stage_3(lake_id=args.lake, all_lakes=args.all)
    elif args.lake or args.all:
        from src.mapview import run_pipeline
        run_pipeline(lake_id=args.lake, all_lakes=args.all)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
