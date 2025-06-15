#!/usr/bin/env python3
"""
Simple test to verify LocalStorageDb integration works correctly
"""

import os
import shutil
import uuid
from datetime import datetime

from db import LocalStorageDb

def test_fetch_save_update_episodes():
    db = LocalStorageDb({'namespace': 'transcript_queue', 'storage_path': './test_data'})
    db.add_collection('episodes')
    episodes = db.episodes

    data = [{
        "title": 'title',
        "url": 'url1.com',
        "type": "youtube",
        "status": "todo",
        "published_date": datetime.now().strftime("%Y-%m-%d")
    }]
    for ep in data:
        episodes.upsert(ep)

    match_ep = db.episodes.find_one({'url': 'url1.com'})
    assert match_ep['title'] == 'title', 'can insert'

    match_ep['title'] = 'updated_title'
    db.episodes.upsert(match_ep)
    assert db.episodes.find_one({'url': 'url1.com'})['title'] == 'updated_title', 'can update'

    episodes.remove({ 'url': 'url' })


def test_basic_ops():
    # Create database
    db = LocalStorageDb({'namespace': 'myapp', 'storage_path': './test_data'})

    # Add collection
    db.add_collection('users')

    # Insert some data
    users = db.users
    users.upsert({'_id': '1', 'name': 'Alice', 'age': 30, 'score': 85})
    users.upsert({'_id': '2', 'name': 'Bob', 'age': 30, 'score': 92})
    users.upsert({'_id': '3', 'name': 'Charlie', 'age': 35, 'score': 78})

    # Find all users
    all_users = users.find().fetch()
    print("All users:", all_users)

    match_users = users.find({'age': 30}).fetch()
    print('Matching age users:', match_users)

    # Find with sorting by age (ascending)
    sorted_by_age = users.find({}, {'sort': {'age': 1}}).fetch()
    print("Sorted by age (asc):", [u['name'] for u in sorted_by_age])

    # Find with sorting by score (descending)
    sorted_by_score = users.find({}, {'sort': {'score': -1}}).fetch()
    print("Sorted by score (desc):", [f"{u['name']}: {u['score']}" for u in sorted_by_score])

    # Find with array-style sort specification
    sorted_array_style = users.find({}, {'sort': [['age', 'desc'], ['name', 'asc']]}).fetch()
    print("Sorted by age desc, name asc:", [f"{u['name']}: {u['age']}" for u in sorted_array_style])

    # Find with limit and skip
    limited = users.find({}, {'sort': {'age': 1}, 'limit': 2, 'skip': 1}).fetch()
    print("Limited results:", [u['name'] for u in limited])

    # Find one
    alice = users.find_one({'_id': '1'})
    print("Alice:", alice)

    alice = users.find_one({'name': 'Alice'})
    print("Alice:", alice)

    # Find no match
    nomatch = users.find({'name': 'John'}).fetch()
    print("No matching users:", nomatch)

    # Find one no match
    nomatch = users.find_one({'name': 'John'})
    print("No matching user:", nomatch)

    # Remove
    users.remove('2')

    # update
    users.upsert({'_id': '1', 'name': 'Alexis', 'age': 30, 'score': 85})

    # Check remaining users
    remaining = users.find().fetch()
    print("Remaining users:", [u['name'] for u in remaining])

    # reload
    db = LocalStorageDb({'namespace': 'myapp', 'storage_path': './test_data'})
    db.add_collection('users')
    alice = db.users.find_one({'name': 'Alexis'})
    print("Alice:", alice)

def test_basic_functionality():
    """Test basic LocalStorageDb functionality"""
    print("Testing LocalStorageDb basic functionality...")

    # Clean up any existing test data
    if os.path.exists('./test_data'):
        shutil.rmtree('./test_data')

    # Initialize database
    db = LocalStorageDb({'namespace': 'test_queue', 'storage_path': './test_data'})
    db.add_collection('episodes')

    # Test data
    test_episode = {
        '_id': 'test-1',
        'title': 'Test Episode',
        'url': 'https://example.com/test',
        'status': 'todo',
        'type': 'youtube',
        'published_date': '2023-01-01'
    }

    # Test upsert
    db.episodes.upsert(test_episode)
    print("✓ Upsert operation successful")

    # Test find
    episodes = db.episodes.find().fetch()
    assert len(episodes) == 1, f"Expected 1 episode, got {len(episodes)}"
    assert episodes[0]['title'] == 'Test Episode', f"Expected 'Test Episode', got {episodes[0]['title']}"
    print("✓ Find operation successful")

    # Test status filtering (simulating load_episodes functionality)
    episodes_by_status = [ep for ep in episodes if ep['status'] == 'todo']
    assert len(episodes_by_status) == 1, f"Expected 1 todo episode, got {len(episodes_by_status)}"
    print("✓ Status filtering successful")

    # Test update
    test_episode['status'] = 'done'
    db.episodes.upsert(test_episode)

    updated_episodes = db.episodes.find().fetch()
    assert updated_episodes[0]['status'] == 'done', f"Expected 'done', got {updated_episodes[0]['status']}"
    print("✓ Update operation successful")

    # Test remove
    db.episodes.remove('test-1')
    final_episodes = db.episodes.find().fetch()
    assert len(final_episodes) == 0, f"Expected 0 episodes after removal, got {len(final_episodes)}"
    print("✓ Remove operation successful")

    print("All basic functionality tests passed!")

def test_queue_functionality():
    """Test queue-specific functionality"""
    print("\nTesting queue functionality...")

    # Clean up any existing test data
    if os.path.exists('./test_data'):
        shutil.rmtree('./test_data')

    # Initialize database
    db = LocalStorageDb({'namespace': 'test_queue', 'storage_path': './test_data'})
    db.add_collection('queue')

    # Test multiple items
    test_items = [
        {
            '_id': 'item-1',
            'url': 'https://example.com/1',
            'status': 'todo',
            'title': 'Item 1'
        },
        {
            '_id': 'item-2',
            'url': 'https://example.com/2',
            'status': 'queued',
            'title': 'Item 2'
        }
    ]

    # Add items to queue
    for item in test_items:
        db.queue.upsert(item)

    # Test finding by status (simulating queue filtering)
    all_items = db.queue.find().fetch()
    queued_items = [item for item in all_items if item['status'] == 'queued']
    todo_items = [item for item in all_items if item['status'] == 'todo']

    assert len(all_items) == 2, f"Expected 2 total items, got {len(all_items)}"
    assert len(queued_items) == 1, f"Expected 1 queued item, got {len(queued_items)}"
    assert len(todo_items) == 1, f"Expected 1 todo item, got {len(todo_items)}"
    print("✓ Queue filtering successful")

    # Test status update (simulating move_to_status)
    for item in all_items:
        if item['url'] == 'https://example.com/1':
            item['status'] = 'processing'
            db.queue.upsert(item)
            break

    updated_items = db.queue.find().fetch()
    processing_items = [item for item in updated_items if item['status'] == 'processing']
    assert len(processing_items) == 1, f"Expected 1 processing item, got {len(processing_items)}"
    print("✓ Status update successful")

    print("All queue functionality tests passed!")

def cleanup():
    """Clean up test data"""
    if os.path.exists('./test_data'):
        shutil.rmtree('./test_data')
    print("✓ Cleanup completed")

if __name__ == "__main__":
    try:
        test_basic_functionality()
        test_queue_functionality()

        test_basic_ops()
        test_fetch_save_update_episodes()
        print("\n🎉 All tests passed successfully!")
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
    finally:
        cleanup()
