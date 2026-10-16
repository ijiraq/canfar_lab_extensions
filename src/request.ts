import { URLExt } from '@jupyterlab/coreutils';
import { ServerConnection } from '@jupyterlab/services';

export async function canfarRequest(
  path: string,
  init: RequestInit = {}
): Promise<Response> {
  const settings = ServerConnection.makeSettings();
  const url = URLExt.join(settings.baseUrl, 'canfar', path);
  const response = await ServerConnection.makeRequest(url, init, settings);
  return response;
}
