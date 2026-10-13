// Calls to the Stand server. The browser talks only to this origin; Ditto and the
// advisor service are reached by the server.

export class ApiError extends Error {
  constructor(message, status, code) {
    super(message);
    this.status = status;
    this.code = code;
  }
}

async function parse(response) {
  let data = null;
  try {
    data = await response.json();
  } catch (error) {
    data = null;
  }
  if (!response.ok) {
    const message = (data && data.error) || `Стенд ответил с кодом ${response.status}`;
    throw new ApiError(message, response.status, data && data.code);
  }
  return data;
}

export async function getJSON(path) {
  let response;
  try {
    response = await fetch(path, { cache: 'no-store' });
  } catch (error) {
    throw new ApiError('Нет связи со стендом', 0, 'network');
  }
  return parse(response);
}

/** POST /api/scenario with {preset} | {action} | {set} | {step}; resolves with the new scenario. */
export async function postScenario(body) {
  let response;
  try {
    response = await fetch('/api/scenario', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
  } catch (error) {
    throw new ApiError('Нет связи со стендом', 0, 'network');
  }
  return parse(response);
}

export const getState = () => getJSON('/api/state');
export const getScenario = () => getJSON('/api/scenario');
export const getAdvisor = () => getJSON('/api/advisor');
export const getParams = () => getJSON('/api/params');

/** Geometry for the views, or null while model/geometry.json does not exist. */
export async function getGeometry() {
  try {
    return await getJSON('/api/geometry');
  } catch (error) {
    return null;
  }
}
