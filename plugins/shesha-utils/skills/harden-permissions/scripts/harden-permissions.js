/**
 * Harden Shesha permissioned objects via the UI.
 *
 * Usage:
 *   node harden-permissions.js <baseUrl> <username> <password> [--dry-run]
 *
 * Example:
 *   node harden-permissions.js http://localhost:3000 admin "#Pass1"
 *
 * Requires: playwright (globally installed via @playwright/test)
 */

const PLAYWRIGHT_PATH = (() => {
  try {
    return require.resolve('playwright');
  } catch {
    const { execSync } = require('child_process');
    const globalRoot = execSync('npm root -g', { encoding: 'utf-8' }).trim();
    return require.resolve(`${globalRoot}/@playwright/test/node_modules/playwright`);
  }
})();

const { chromium } = require(PLAYWRIGHT_PATH);

// ── Configuration ──────────────────────────────────────────────────────────────

const CHANGES = [
  // Full class-level app:Configurator
  { service: 'ProcessMonitor', scope: 'class', accessLevel: 'requiresPermissions' },
  { service: 'DeviceForceUpdate', scope: 'class', accessLevel: 'requiresPermissions' },
  { service: 'DeviceRegistration', scope: 'class', accessLevel: 'requiresPermissions' },
  { service: 'SmsGateways', scope: 'class', accessLevel: 'requiresPermissions' },

  // AnyAuthenticated at class + app:Configurator on write methods
  {
    service: 'Area',
    scope: 'methods',
    classAccess: 'anyAuthenticated',
    methods: ['Create', 'Delete', 'Update', 'MoveArea'],
  },
  {
    service: 'ConfigurableComponent',
    scope: 'methods',
    classAccess: 'anyAuthenticated',
    methods: ['Create', 'Delete', 'Update', 'UpdateSettings'],
  },
  {
    service: 'EntityConfig',
    scope: 'methods',
    classAccess: 'anyAuthenticated',
    methods: ['Create', 'Delete', 'Update', 'RemoveConfigurationsOfMissingClasses'],
  },
  {
    service: 'EntityProperty',
    scope: 'methods',
    classAccess: 'anyAuthenticated',
    methods: ['Create', 'Delete', 'Update'],
  },
  {
    service: 'ReferenceList',
    scope: 'methods',
    classAccess: 'anyAuthenticated',
    methods: ['Create', 'Delete', 'Update', 'ClearCacheFull'],
  },
  {
    service: 'ShaRole',
    scope: 'methods',
    classAccess: 'anyAuthenticated',
    methods: ['Create', 'Delete', 'Update'],
  },
  {
    service: 'Notification',
    scope: 'methods',
    classAccess: 'anyAuthenticated',
    methods: ['Publish'],
  },
  {
    service: 'NotificationMessage',
    scope: 'methods',
    classAccess: 'anyAuthenticated',
    methods: ['Create', 'Delete', 'Update'],
  },
  {
    service: 'QuestionAnswers',
    scope: 'methods',
    classAccess: 'anyAuthenticated',
    methods: ['Delete'],
  },

  // Specific method restrictions only (no class-level change)
  {
    service: 'Session',
    scope: 'methods',
    methods: ['ClearPermissionsCache'],
  },
  {
    service: 'UserManagement',
    scope: 'methods',
    methods: ['Create', 'CompleteRegistration'],
  },
];

// ── Helpers ─────────────────────────────────────────────────────────────────────

async function login(page, baseUrl, username, password) {
  await page.goto(`${baseUrl}/login`, { waitUntil: 'networkidle', timeout: 30000 });
  await page.locator('input[placeholder*="username" i]').first().fill(username);
  await page.locator('input[type="password"]').first().fill(password);
  await page.locator('button:has-text("Sign In")').first().click();
  await page.waitForURL(url => !url.toString().includes('login'), { timeout: 15000 });
}

async function navigateToPermissionedObjects(page, baseUrl) {
  await page.goto(`${baseUrl}/dynamic/Shesha/permissioned-objects`, {
    waitUntil: 'networkidle',
    timeout: 30000,
  });
  await page.waitForTimeout(5000);
}

/**
 * Find the index of a top-level service node (level 0) in the tree.
 * Returns the index into the .ant-tree-treenode list.
 */
async function findServiceIndex(page, serviceName) {
  const treeItems = page.locator('.ant-tree-treenode');
  const count = await treeItems.count();
  for (let i = 0; i < count; i++) {
    const text = (await treeItems.nth(i).innerText().catch(() => '')).trim();
    const level = await treeItems.nth(i).evaluate(el => {
      const indent = el.querySelector('.ant-tree-indent');
      return indent ? indent.children.length : 0;
    });
    if (level === 0 && text.startsWith(serviceName)) {
      return i;
    }
  }
  return -1;
}

/**
 * Select a top-level service node by clicking its tree title.
 */
async function selectServiceNode(page, serviceName) {
  const idx = await findServiceIndex(page, serviceName);
  if (idx === -1) throw new Error(`Service "${serviceName}" not found in tree`);
  const treeItems = page.locator('.ant-tree-treenode');
  await treeItems.nth(idx).locator('.ant-tree-title').first().click();
  await page.waitForTimeout(1500);
}

/**
 * Select a child method node under an already-expanded service.
 * Walks tree nodes after the service node, looking for level-1 nodes
 * whose text starts with the method name.
 */
async function selectMethodNode(page, serviceName, methodName) {
  const treeItems = page.locator('.ant-tree-treenode');
  const count = await treeItems.count();
  const serviceIdx = await findServiceIndex(page, serviceName);
  if (serviceIdx === -1) throw new Error(`Service "${serviceName}" not found`);

  for (let i = serviceIdx + 1; i < count; i++) {
    const level = await treeItems.nth(i).evaluate(el => {
      const indent = el.querySelector('.ant-tree-indent');
      return indent ? indent.children.length : 0;
    });
    // Hit the next top-level service — method not found
    if (level === 0) break;

    const text = (await treeItems.nth(i).innerText().catch(() => '')).trim();
    if (level === 1 && text.startsWith(methodName)) {
      await treeItems.nth(i).locator('.ant-tree-title').first().click();
      await page.waitForTimeout(1500);
      return;
    }
  }
  throw new Error(`Method "${methodName}" not found under "${serviceName}"`);
}

async function expandServiceNode(page, serviceName) {
  const idx = await findServiceIndex(page, serviceName);
  if (idx === -1) throw new Error(`Cannot expand: service "${serviceName}" not found`);

  const treeItems = page.locator('.ant-tree-treenode');
  const node = treeItems.nth(idx);
  const isOpen = await node.evaluate(el =>
    el.classList.contains('ant-tree-treenode-switcher-open')
  );
  if (!isOpen) {
    const switcher = node.locator('.ant-tree-switcher');
    if ((await switcher.count()) > 0) {
      await switcher.first().click();
      await page.waitForTimeout(2000);
    }
  }
}

async function collapseServiceNode(page, serviceName) {
  const idx = await findServiceIndex(page, serviceName);
  if (idx === -1) return;

  const treeItems = page.locator('.ant-tree-treenode');
  const node = treeItems.nth(idx);
  const isOpen = await node.evaluate(el =>
    el.classList.contains('ant-tree-treenode-switcher-open')
  );
  if (isOpen) {
    const switcher = node.locator('.ant-tree-switcher');
    if ((await switcher.count()) > 0) {
      await switcher.first().click();
      await page.waitForTimeout(500);
    }
  }
}

async function clickEdit(page) {
  await page.locator('button:has-text("Edit")').first().click();
  await page.waitForTimeout(1500);
}

async function setAccessLevel(page, level) {
  const accessSelect = page.locator('.ant-select').first();
  await accessSelect.click();
  await page.waitForTimeout(500);
  await page.locator(`.ant-select-item-option:has-text("${level}")`).first().click();
  await page.waitForTimeout(1000);
}

async function selectPermissionAppConfigurator(page) {
  const permissionsSelect = page.locator('.ant-select').nth(1);
  await permissionsSelect.locator('.ant-select-selection-search-input').click();
  await page.waitForTimeout(500);
  await page.keyboard.type('app', { delay: 80 });
  await page.waitForTimeout(2000);

  const configuratorNode = page
    .locator('.ant-select-dropdown:visible .ant-tree-treenode:has-text("Application configurator")')
    .first();

  if ((await configuratorNode.count()) === 0) {
    throw new Error('Could not find "Application configurator" in permissions dropdown');
  }

  const checkbox = configuratorNode.locator('.ant-tree-checkbox');
  const isChecked = await checkbox.evaluate(el =>
    el.classList.contains('ant-tree-checkbox-checked')
  );
  if (!isChecked) {
    await checkbox.click();
    await page.waitForTimeout(1000);
  }

  await page.keyboard.press('Escape');
  await page.waitForTimeout(500);
}

async function clickSave(page) {
  await page.locator('button:has-text("Save")').first().click();
  await page.waitForTimeout(2000);
  try {
    await page.locator('text=Data saved successfully').waitFor({ timeout: 5000 });
  } catch {
    const body = await page.locator('body').innerText();
    if (body.includes('Error') || body.includes('error')) {
      console.error('  WARNING: Possible error after save');
    }
  }
}

async function setRequiresConfigurator(page, label) {
  await clickEdit(page);
  await setAccessLevel(page, 'Requires permissions');
  await selectPermissionAppConfigurator(page);
  await clickSave(page);
  console.log(`  + ${label} -> Requires permissions [app:Configurator]`);
}

async function setAnyAuthenticated(page, label) {
  await clickEdit(page);
  await setAccessLevel(page, 'Any authenticated');
  await clickSave(page);
  console.log(`  + ${label} -> Any authenticated`);
}

function isAlreadyPermissioned(bodyText) {
  return bodyText.includes('Requires permissions') && bodyText.includes('app:Configurator');
}

// ── Main ────────────────────────────────────────────────────────────────────────

(async () => {
  const args = process.argv.slice(2);
  if (args.length < 3) {
    console.log('Usage: node harden-permissions.js <baseUrl> <username> <password> [--dry-run]');
    process.exit(1);
  }

  const [baseUrl, username, password] = args;
  const dryRun = args.includes('--dry-run');

  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext();
  const page = await context.newPage();

  let successes = 0;
  let failures = 0;
  let skipped = 0;

  try {
    console.log(`Logging in to ${baseUrl}...`);
    await login(page, baseUrl, username, password);

    console.log('Navigating to permissioned-objects...\n');
    await navigateToPermissionedObjects(page, baseUrl);

    for (const change of CHANGES) {
      console.log(`-- ${change.service} --`);

      if (change.scope === 'class') {
        await selectServiceNode(page, change.service);

        if (dryRun) {
          console.log(`  [DRY RUN] Would set to Requires permissions [app:Configurator]`);
          continue;
        }

        const body = await page.locator('body').innerText();
        if (isAlreadyPermissioned(body)) {
          console.log(`  = ${change.service} already permissioned, skipping`);
          skipped++;
          continue;
        }

        try {
          await setRequiresConfigurator(page, change.service);
          successes++;
        } catch (err) {
          console.error(`  X ${change.service}: ${err.message}`);
          failures++;
        }

      } else if (change.scope === 'methods') {
        // Optionally set class-level access
        if (change.classAccess === 'anyAuthenticated') {
          await selectServiceNode(page, change.service);

          if (dryRun) {
            console.log(`  [DRY RUN] Would set class to Any authenticated`);
          } else {
            const body = await page.locator('body').innerText();
            if (body.includes('Any authenticated')) {
              console.log(`  = ${change.service} (class) already Any authenticated`);
              skipped++;
            } else {
              try {
                await setAnyAuthenticated(page, `${change.service} (class)`);
                successes++;
              } catch (err) {
                console.error(`  X ${change.service} (class): ${err.message}`);
                failures++;
              }
            }
          }
        }

        // Expand the service to reveal child methods
        await expandServiceNode(page, change.service);

        for (const method of change.methods) {
          try {
            await selectMethodNode(page, change.service, method);

            if (dryRun) {
              console.log(`  [DRY RUN] Would set ${method} to Requires permissions [app:Configurator]`);
              continue;
            }

            const body = await page.locator('body').innerText();
            if (isAlreadyPermissioned(body)) {
              console.log(`  = ${method} already permissioned, skipping`);
              skipped++;
              continue;
            }

            await setRequiresConfigurator(page, method);
            successes++;
          } catch (err) {
            console.error(`  X ${method}: ${err.message}`);
            failures++;
          }
        }

        await collapseServiceNode(page, change.service);
      }
    }

    console.log(`\n-- Summary --`);
    console.log(`  Successes: ${successes}`);
    console.log(`  Skipped (already set): ${skipped}`);
    console.log(`  Failures: ${failures}`);
    if (dryRun) console.log('  (dry run — no changes were made)');

  } catch (err) {
    console.error('Fatal error:', err.message);
    await page.screenshot({ path: '/tmp/harden-error.png', fullPage: true });
    console.error('Screenshot saved to /tmp/harden-error.png');
    process.exit(1);
  } finally {
    await browser.close();
  }
})();
