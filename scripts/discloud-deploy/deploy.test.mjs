import assert from "node:assert/strict";
import test from "node:test";
import { deployWithClient, main } from "./deploy.mjs";

const validEnv = {
  DISCLOUD_TOKEN: "test-token-do-not-print",
  DISCLOUD_APP_ID: "1234567890",
  TAG_NAME: "v1.2.3",
  DISCLOUD_ARCHIVE: "target/discloud/quimia-api.zip",
};

test("logs in and updates the selected app with the release archive", async () => {
  const calls = [];
  const client = {
    async login(token) {
      calls.push(["login", token]);
    },
    apps: {
      async update(appId, options) {
        calls.push(["update", appId, options]);
      },
    },
  };

  await deployWithClient(client, validEnv);

  assert.deepEqual(calls, [
    ["login", validEnv.DISCLOUD_TOKEN],
    ["update", validEnv.DISCLOUD_APP_ID, { file: validEnv.DISCLOUD_ARCHIVE }],
  ]);
});

for (const [name, overrides] of [
  ["token", { DISCLOUD_TOKEN: "" }],
]) {
  test(`rejects a missing ${name} before using the client`, async () => {
    let calls = 0;
    const client = {
      async login() {
        calls += 1;
      },
      apps: {
        async update() {
          calls += 1;
        },
      },
    };

    await assert.rejects(deployWithClient(client, { ...validEnv, ...overrides }));
    assert.equal(calls, 0);
  });
}

test("creates the first app after the SDK returns an empty app map", async () => {
  const calls = [];
  const client = {
    async login(token) {
      calls.push(["login", token]);
    },
    apps: {
      async fetch(scope) {
        calls.push(["fetch-apps", scope]);
        return new Map();
      },
      async create(options) {
        calls.push(["create", options]);
      },
    },
  };

  const result = await deployWithClient(client, { ...validEnv, DISCLOUD_APP_ID: "" });

  assert.equal(result, "created");
  assert.deepEqual(calls, [
    ["login", validEnv.DISCLOUD_TOKEN],
    ["fetch-apps", "all"],
    ["create", { file: validEnv.DISCLOUD_ARCHIVE }],
  ]);
});

test("refuses to create a duplicate when an app exists but its ID is not configured", async () => {
  const calls = [];
  let createCalls = 0;
  const client = {
    async login() {},
    apps: {
      async fetch(scope) {
        calls.push(["fetch-apps", scope]);
        return new Map([["existing-app-id", {}]]);
      },
      async create() {
        createCalls += 1;
      },
    },
  };

  await assert.rejects(
    deployWithClient(client, { ...validEnv, DISCLOUD_APP_ID: "" }),
    /DISCLOUD_APP_ID/,
  );
  assert.deepEqual(calls, [["fetch-apps", "all"]]);
  assert.equal(createCalls, 0);
});

test("fails closed when the SDK returns an unexpected app list shape", async () => {
  let createCalls = 0;
  const client = {
    async login() {},
    apps: {
      async fetch() {
        return { apps: [] };
      },
      async create() {
        createCalls += 1;
      },
    },
  };

  await assert.rejects(
    deployWithClient(client, { ...validEnv, DISCLOUD_APP_ID: "" }),
    /Could not verify the Discloud app list/,
  );
  assert.equal(createCalls, 0);
});

test("rejects a non-release tag before using the client", async () => {
  let calls = 0;
  const client = {
    async login() {
      calls += 1;
    },
    apps: {
      async update() {
        calls += 1;
      },
    },
  };

  await assert.rejects(deployWithClient(client, { ...validEnv, TAG_NAME: "main" }));
  assert.equal(calls, 0);
});

test("main reports only a fixed message when the SDK rejects an upload", async () => {
  const stderr = [];
  const sdkError = new Error(`request failed for ${validEnv.DISCLOUD_TOKEN}`);
  const code = await main(
    validEnv,
    async () => ({
      async login() {},
      apps: {
        async update() {
          throw sdkError;
        },
      },
    }),
    (message) => stderr.push(message),
  );

  assert.equal(code, 1);
  assert.deepEqual(stderr, ["Discloud upload failed"]);
  assert.equal(stderr.join("\n").includes(validEnv.DISCLOUD_TOKEN), false);
});

test("main validates the tag before constructing the SDK client", async () => {
  let clientsCreated = 0;
  const stderr = [];
  const code = await main(
    { ...validEnv, TAG_NAME: "main" },
    async () => {
      clientsCreated += 1;
      return {};
    },
    (message) => stderr.push(message),
  );

  assert.equal(code, 1);
  assert.equal(clientsCreated, 0);
  assert.deepEqual(stderr, ["Discloud upload failed"]);
});
