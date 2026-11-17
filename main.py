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
    # stage1_register.py logic will be invoked here
    pass


def run_stage_3():
    print("=" * 60)
    print("Stage 3: Generating Satellite Map, Verification & Interactive View...")
    print("=" * 60)
    from src.mapview import generate_all_outputs
    return generate_all_outputs()


def main():
    parser = argparse.ArgumentParser(description="HMDA Lake Register Pipeline")
    parser.add_argument("--stage", type=int, choices=[1, 2, 3, 4, 5], help="Run a specific stage")
    parser.add_argument("--all", action="store_true", help="Run all stages")
    args = parser.parse_args()

    if args.stage == 1:
        run_stage_1()
    elif args.stage == 3:
        run_stage_3()
    elif args.all:
        print("Running full pipeline...")
        run_stage_1()
        run_stage_3()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
