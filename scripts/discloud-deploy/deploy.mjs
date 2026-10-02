import { pathToFileURL } from "node:url";
import { resolve } from "node:path";

const releaseTagPattern = /^v\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$/;

class SafeDeploymentError extends Error {}

export function validateDeploymentConfig(env) {
  const {
    DISCLOUD_TOKEN: token,
    DISCLOUD_APP_ID: appId,
    TAG_NAME: tagName,
    DISCLOUD_ARCHIVE: archivePath,
  } = env;

  if (!token || !tagName || !archivePath) {
    throw new Error("Missing deploy configuration");
  }
  if (!releaseTagPattern.test(tagName)) {
    throw new Error("Invalid release tag");
  }

  return { token, appId, archivePath };
}

export async function deployWithClient(client, env) {
  const { token, appId, archivePath } = validateDeploymentConfig(env);
  await client.login(token);

  if (appId) {
    await client.apps.update(appId, { file: archivePath });
    return "updated";
  }

  const apps = await client.apps.fetch("all");
  if (!(apps instanceof Map)) {
    throw new SafeDeploymentError(
      "Could not verify the Discloud app list; first-app creation was aborted.",
    );
  }
  if (apps.size > 0) {
    throw new SafeDeploymentError(
      "DISCLOUD_APP_ID is missing, but this Discloud account already has apps. Set it to the Quimia app ID to update without creating a duplicate.",
    );
  }

  await client.apps.create({ file: archivePath });
  return "created";
}

async function loadDiscloudClient() {
  const { discloud } = await import("discloud.app");
  return discloud;
}

export async function main(
  env = process.env,
  clientFactory = loadDiscloudClient,
  writeError = (message) => console.error(message),
  writeOutput = (message) => console.log(message),
) {
  try {
    validateDeploymentConfig(env);
    const client = await clientFactory();
    const result = await deployWithClient(client, env);
    if (result === "created") {
      writeOutput(
        "First Discloud app created. Set DISCLOUD_APP_ID from the Discloud dashboard before the next release.",
      );
    } else {
      writeOutput("Discloud app updated");
    }
    return 0;
  } catch (error) {
    writeError(
      error instanceof SafeDeploymentError
        ? error.message
        : "Discloud upload failed",
    );
    return 1;
  }
}

if (process.argv[1]
    && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  main().then((exitCode) => {
    process.exitCode = exitCode;
  });
}
