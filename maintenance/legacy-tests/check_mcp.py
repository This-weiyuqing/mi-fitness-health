import asyncio
import json
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def main():
    root = Path(__file__).resolve().parents[2]
    data = root / 'work/local-production-validation/state/data'
    parameters = StdioServerParameters(
        command=r'C:/Users/35861/AppData/Local/Programs/DockerDesktop/resources/bin/docker.exe',
        args=['--context','desktop-linux','run','--rm','-i','--network','none','--read-only',
              '--mount',f'type=bind,source={data},target=/health,readonly',
              '--entrypoint','python','local/mi-fitness-nas:20261016','/opt/health/readonly.py'])
    async with stdio_client(parameters) as (read, write):
        async with ClientSession(read,write) as session:
            await session.initialize()
            tools = await session.list_tools()
            result = await session.call_tool('get_health_records',arguments={'kind':'daily_activity','start_date':'2026-10-15','end_date':'2026-10-15'})
            payload = result.structuredContent or json.loads(result.content[0].text)
            denied = await session.call_tool('get_health_records',arguments={'kind':'api_keys','start_date':'2026-10-15','end_date':'2026-10-15'})
            report = {'mcp_handshake':True,'tools':[t.name for t in tools.tools],
                      'read_only_annotation':all(t.annotations.readOnlyHint for t in tools.tools),
                      'real_daily_matches_phone':not result.isError and payload['data'][0]['steps']==4691 and payload['data'][0]['active_kcal']==596,
                      'credential_query_denied':bool(denied.isError),'container_network':'none','database_mount':'read_only'}
            print(json.dumps(report))
            (root/'work/deployment-tests/mcp-proof.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
            if report['tools']!=['get_health_records'] or not report['real_daily_matches_phone'] or not denied.isError:
                raise SystemExit(1)


asyncio.run(main())
