load('ext://restart_process', 'docker_build_with_restart')

# Backend hot-reload
docker_build_with_restart(
    'sre-copilot/backend',
    'src/backend',
    entrypoint=['uvicorn', 'backend.main:app', '--host', '0.0.0.0', '--port', '8000', '--reload'],
    live_update=[
        sync('src/backend', '/app'),
        run('pip install -r requirements.txt', trigger=['src/backend/requirements.txt']),
    ],
)

docker_build('sre-copilot/frontend', 'src/frontend', live_update=[
    sync('src/frontend/src', '/app/src'),
    run('npm install', trigger=['src/frontend/package.json']),
])

k8s_yaml(helm('helm/backend',  values=['helm/backend/values-dev.yaml']))
k8s_yaml(helm('helm/frontend', values=['helm/frontend/values-dev.yaml']))

k8s_resource('backend',  port_forwards=['8000:8000'], labels=['apps'])
k8s_resource('frontend', port_forwards=['3000:3000'], labels=['apps'])
