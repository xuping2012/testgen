import requests
import json

print('=' * 80)
print('Step 1: Trigger Requirement Analysis')
print('=' * 80)

# Trigger requirement analysis (Phase 1)
response = requests.post(
    'http://localhost:5000/api/generate',
    json={'requirement_id': 7}
)

print(f'Status: {response.status_code}')
data = response.json()
print(f'Response:')
print(json.dumps(data, indent=2, ensure_ascii=False))

if response.status_code == 200:
    print('\n[OK] Requirement analysis completed!')
    task_id = data.get('task_id')
    status = data.get('status')
    print(f'\nTask ID: {task_id}')
    print(f'Status: {status}')
    print(f'\nAnalysis results include:')
    if 'analysis_result' in data:
        result = data['analysis_result']
        modules = result.get('modules', [])
        items = result.get('items', [])
        points = result.get('points', [])
        print(f'  - Functional Modules: {len(modules)}')
        print(f'  - Test Items: {len(items)}')
        print(f'  - Test Points: {len(points)}')
        
        # Save task_id for next step
        with open('task_id.txt', 'w') as f:
            f.write(task_id)
        print(f'\nTask ID saved to task_id.txt')
else:
    print(f'\n[FAIL] Analysis failed: {data.get("error", "Unknown error")}')
