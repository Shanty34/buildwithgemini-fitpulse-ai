#!/usr/bin/env python3
"""Seed script to populate Firestore with sample workout routines for FitPulse AI.

Project ID is explicitly hardcoded as a string per deployment instructions.
"""

from __future__ import annotations

import time
from google.cloud import firestore

# Hardcoded project ID string required for Agent Platform deployment compatibility
PROJECT_ID = "qwiklabs-gcp-01-39fe799c3cd6"
COLLECTION_NAME = "workouts"

SEED_WORKOUTS = [
    {
        "workout_id": "chest_triceps_power",
        "title": "Upper Body Chest & Triceps Power",
        "workout_type": "Strength",
        "muscle_groups": ["Chest", "Triceps", "Shoulders"],
        "difficulty": "Intermediate",
        "duration_minutes": 45,
        "calories_burned": 350,
        "exercises": [
            {"name": "Barbell Bench Press", "sets": 4, "reps": 8},
            {"name": "Incline Dumbbell Press", "sets": 3, "reps": 12},
            {"name": "Cable Chest Flyes", "sets": 3, "reps": 15},
            {"name": "Tricep Rope Pushdowns", "sets": 4, "reps": 15},
        ],
        "low_impact": True,
        "notes": "Focused on chest hypertrophy and tricep isolation with low joint impact.",
    },
    {
        "workout_id": "knee_friendly_legs",
        "title": "Knee-Friendly Lower Body & Core",
        "workout_type": "Strength",
        "muscle_groups": ["Legs", "Quads", "Glutes", "Core"],
        "difficulty": "Beginner",
        "duration_minutes": 40,
        "calories_burned": 280,
        "exercises": [
            {"name": "Glute Bridges", "sets": 3, "reps": 15},
            {"name": "Chair Wall Sits", "sets": 3, "reps": 45},
            {"name": "Romanian Deadlifts (Light DB)", "sets": 3, "reps": 12},
            {"name": "Standing Calf Raises", "sets": 4, "reps": 20},
            {"name": "Plank Hold", "sets": 3, "reps": 60},
        ],
        "low_impact": True,
        "notes": "Low-impact leg workout specifically designed for knee sensitivity and core stability.",
    },
    {
        "workout_id": "zone2_cycling",
        "title": "Zone 2 Steady Endurance Cycling",
        "workout_type": "Endurance",
        "muscle_groups": ["Legs", "Quads", "Cardio"],
        "difficulty": "Beginner",
        "duration_minutes": 50,
        "calories_burned": 420,
        "exercises": [
            {"name": "Stationary Cycling (Zone 2 HR 135-147 BPM)", "sets": 1, "reps": 50},
        ],
        "low_impact": True,
        "notes": "Aerobic base building endurance ride with steady cadence and zero knee impact.",
    },
    {
        "workout_id": "back_biceps_pull",
        "title": "Pull Power: Back & Biceps",
        "workout_type": "Strength",
        "muscle_groups": ["Back", "Biceps", "Rear Delts"],
        "difficulty": "Intermediate",
        "duration_minutes": 45,
        "calories_burned": 340,
        "exercises": [
            {"name": "Lat Pulldowns", "sets": 4, "reps": 10},
            {"name": "Seated Cable Rows", "sets": 3, "reps": 12},
            {"name": "Dumbbell Hammer Curls", "sets": 3, "reps": 12},
            {"name": "Face Pulls", "sets": 4, "reps": 15},
        ],
        "low_impact": True,
        "notes": "Upper body pulling routine for back thickness and arm strength.",
    },
]


def seed_firestore() -> None:
    """Populates Firestore collection with seed workout routines using a retry loop."""
    db = firestore.Client(project=PROJECT_ID)
    collection_ref = db.collection(COLLECTION_NAME)

    print(f"🌱 Seeding Firestore collection '{COLLECTION_NAME}' in project '{PROJECT_ID}'...")
    for workout in SEED_WORKOUTS:
        doc_id = workout["workout_id"]
        for attempt in range(5):
            try:
                collection_ref.document(doc_id).set(workout)
                print(f"   - Seeded document: {doc_id} ('{workout['title']}')")
                break
            except Exception as e:
                if attempt == 4:
                    raise e
                time.sleep(2)

    print("✅ Firestore seeding completed successfully!")


if __name__ == "__main__":
    seed_firestore()
