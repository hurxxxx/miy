// Read reviewed blobs with the pinned parser. Never load application/config code.
import { createRequire } from 'node:module';
import path from 'node:path';
import { readFileSync } from 'node:fs';
import { pathToFileURL } from 'node:url';

const require = createRequire(import.meta.url);
const ts = require('typescript');
const p = path.posix;
const code = /\.(?:[cm]?[jt]sx?)$/;
const scan = /\.(?:[cm]?[jt]sx?|css|html|md|mdx)$/;
const fail = (sourcePath) => {
  const error = new Error('unresolved_portal_build_input');
  error.sourcePath = sourcePath;
  throw error;
};
const literal = (node) =>
  node && ts.isStringLiteralLike(node) ? node.text : fail();
const importMeta = (node) =>
  node &&
  ts.isMetaProperty(node) &&
  node.keywordToken === ts.SyntaxKind.ImportKeyword &&
  node.name.text === 'meta';
const importMetaField = (node, field) =>
  node &&
  ts.isPropertyAccessExpression(node) &&
  importMeta(node.expression) &&
  node.name.text === field;

export function sharedUiConsumers(files) {
  if (!files || typeof files !== 'object' || Array.isArray(files)) fail();
  const names = Object.keys(files);
  const exists = (name) => Object.hasOwn(files, name);
  const normalize = (name) => {
    const value = p.normalize(name);
    if (value.startsWith('../') || p.isAbsolute(value)) fail();
    return value;
  };
  const text = (name) =>
    typeof files[name] === 'string' ? files[name] : fail();
  const parsed = (name) => {
    const tree = ts.createSourceFile(
      name,
      text(name),
      ts.ScriptTarget.Latest,
      true,
    );
    if (tree.parseDiagnostics.length) fail();
    return tree;
  };
  const json = (name) => {
    const result = ts.parseConfigFileTextToJson(name, text(name));
    if (result.error) fail();
    return result.config;
  };
  const manifest = json('package.json');
  const external = new Set(
    Object.keys({ ...manifest.dependencies, ...manifest.devDependencies }),
  );
  const aliases = new Map();
  const configs = new Set();
  function config(name) {
    if (configs.has(name)) fail();
    configs.add(name);
    const value = json(name);
    if (value.extends) {
      if (typeof value.extends !== 'string' || !value.extends.startsWith('.'))
        fail();
      config(normalize(p.join(p.dirname(name), value.extends)));
    }
    for (const [alias, targets] of Object.entries(
      value.compilerOptions?.paths ?? {},
    )) {
      if (
        !Array.isArray(targets) ||
        targets.length !== 1 ||
        typeof targets[0] !== 'string'
      )
        fail();
      if ((alias.match(/\*/g) ?? []).length > 1) fail();
      aliases.set(
        alias,
        normalize(
          p.join(
            p.dirname(name),
            value.compilerOptions?.baseUrl ?? '.',
            targets[0],
          ),
        ),
      );
    }
  }
  config('apps/web/tsconfig.json');
  const vite = 'apps/web/vite.config.mts';
  const viteTree = parsed(vite);
  const viteAliases = new Map();
  let publicDir = 'apps/web/public';
  const propertyName = (node) =>
    ts.isIdentifier(node) || ts.isStringLiteral(node) ? node.text : fail();
  function visitConfig(node) {
    if (ts.isPropertyAssignment(node)) {
      const key = propertyName(node.name);
      if (key === 'alias') {
        if (!ts.isObjectLiteralExpression(node.initializer)) fail();
        for (const item of node.initializer.properties) {
          if (!ts.isPropertyAssignment(item)) fail();
          const call = item.initializer;
          if (
            !ts.isCallExpression(call) ||
            call.expression.getText(viteTree) !== 'path.resolve' ||
            call.arguments.length < 2 ||
            call.arguments[0].getText(viteTree) !== 'import.meta.dirname'
          )
            fail();
          viteAliases.set(
            propertyName(item.name),
            normalize(
              p.join(p.dirname(vite), ...call.arguments.slice(1).map(literal)),
            ),
          );
        }
      } else if (
        key === 'root' &&
        node.initializer.getText(viteTree) !== 'import.meta.dirname'
      )
        fail();
      else if (key === 'publicDir') {
        publicDir =
          node.initializer.kind === ts.SyntaxKind.FalseKeyword
            ? null
            : normalize(p.join(p.dirname(vite), literal(node.initializer)));
      } else if (key === 'rollupOptions') fail(); // Alternate build entries need an explicit owner contract.
    }
    ts.forEachChild(node, visitConfig);
  }
  visitConfig(viteTree);
  function resolveFile(target) {
    target = normalize(target);
    if (exists(target)) return target;
    if (exists(target + '/package.json')) fail(target);
    let candidates;
    if (/\.js$/.test(target))
      candidates = [
        target.slice(0, -3) + '.ts',
        target.slice(0, -3) + '.tsx',
        target.slice(0, -3) + '.d.ts',
      ];
    else if (/\.mjs$/.test(target))
      candidates = [
        target.slice(0, -4) + '.mts',
        target.slice(0, -4) + '.d.mts',
      ];
    else
      candidates = [
        '.ts',
        '.tsx',
        '.mts',
        '.js',
        '.jsx',
        '.mjs',
        '.json',
        '.css',
        '/index.ts',
        '/index.tsx',
        '/index.js',
      ].map((suffix) => target + suffix);
    const found = candidates.filter(exists);
    if (found.length !== 1) fail(target);
    return found[0];
  }
  function resolve(specifier, importer, asset = false) {
    const [bare, query] = specifier.split('?');
    if (
      query !== undefined &&
      !['raw', 'url', 'worker', 'inline'].includes(query)
    )
      fail();
    if (asset && !bare.startsWith('/'))
      return resolveFile(p.join(p.dirname(importer), bare));
    if (bare.startsWith('.') || bare.startsWith('/')) {
      if (bare.startsWith('/')) {
        const source = normalize(p.join('apps/web', bare.slice(1)));
        const publicPath =
          publicDir && normalize(p.join(publicDir, bare.slice(1)));
        if (exists(source)) return source;
        if (publicPath && exists(publicPath)) return publicPath;
        fail();
      }
      return resolveFile(p.join(p.dirname(importer), bare));
    }
    for (const [alias, target] of [...viteAliases].sort(
      ([a], [b]) => b.length - a.length,
    )) {
      if (bare === alias || bare.startsWith(alias + '/'))
        return resolveFile(target + bare.slice(alias.length));
    }
    for (const [alias, target] of [...aliases].sort(
      ([a], [b]) => b.length - a.length,
    )) {
      if (alias.includes('*')) {
        const [prefix, suffix] = alias.split('*');
        if (bare.startsWith(prefix) && bare.endsWith(suffix))
          return resolveFile(
            target.replace(
              '*',
              bare.slice(prefix.length, suffix ? -suffix.length : undefined),
            ),
          );
      } else if (bare === alias) return resolveFile(target);
    }
    if (asset) fail();
    const packageName = bare.startsWith('@')
      ? bare.split('/').slice(0, 2).join('/')
      : bare.split('/')[0];
    if (bare.startsWith('node:') || external.has(packageName)) return null;
    fail();
  }
  const shared = new Set([...configs, 'package.json']);
  const pending = new Set(['apps/web/index.html', vite]);
  if (publicDir)
    for (const name of names)
      if (name.startsWith(publicDir + '/')) shared.add(name);
  const add = (specifier, importer, asset = false) => {
    const target = resolve(specifier, importer, asset);
    if (target) pending.add(target);
  };
  function css(name) {
    const source = text(name).replace(/\/\*[\s\S]*?\*\//g, '');
    const directives = [
      ...source.matchAll(/@(import|reference|plugin|source)\s+([^;]+);/g),
    ];
    if (
      /@config\b/.test(source) ||
      directives.length !==
        [...source.matchAll(/@(import|reference|plugin|source)\b/g)].length
    )
      fail();
    for (const [, directive, raw] of directives) {
      const quoted = raw.match(/^["']([^"']+)["']\s*(.*)$/s);
      if (!quoted) fail();
      const [, specifier, tail] = quoted;
      if (directive === 'source') {
        if (
          tail.trim() ||
          /[*{}!]/.test(specifier) ||
          !specifier.startsWith('.')
        )
          fail();
        const directory = normalize(p.join(p.dirname(name), specifier));
        const inputs = names.filter(
          (item) =>
            (item === directory || item.startsWith(directory + '/')) &&
            scan.test(item),
        );
        if (!inputs.length) fail();
        inputs.forEach((item) => shared.add(item));
      } else {
        if (
          tail.trim() &&
          !(
            directive === 'import' &&
            specifier === 'tailwindcss' &&
            tail.trim() === 'source(none)'
          )
        )
          fail();
        add(specifier, name);
        // Tailwind's implicit cwd scan couples all tracked frontend source. Older
        // baselines must remain full-release until their CSS ownership is split.
        if (specifier === 'tailwindcss' && !tail.trim())
          names
            .filter((item) => scan.test(item))
            .forEach((item) => shared.add(item));
      }
    }
    for (const [, value] of source.matchAll(/url\(\s*([^)]*)\)/g)) {
      const target = value.trim().replace(/^["']|["']$/g, '');
      if (/^(?:data:|https?:|#)/.test(target)) continue;
      if (!target || /\s|var\(/.test(target)) fail();
      add(target, name, true);
    }
  }
  const traversed = new Set();
  while (pending.size) {
    const name = pending.values().next().value;
    pending.delete(name);
    if (traversed.has(name)) continue;
    traversed.add(name);
    shared.add(name);
    if (/\.css$/.test(name)) css(name);
    else if (/\.html$/.test(name)) {
      for (const [, tag, body] of text(name).matchAll(
        /<(script|link)\b([^>]*)>/g,
      )) {
        const value = body.match(
          tag === 'script'
            ? /\bsrc=["']([^"']+)["']/
            : /\bhref=["']([^"']+)["']/,
        )?.[1];
        if (value && !/^(?:https?:|data:|#)/.test(value))
          add(value, name, true);
      }
    } else if (code.test(name)) {
      const tree = parsed(name);
      const developmentRouteProjection = (node) => {
        if (
          name !== 'packages/official-suite-web/vite/ui-routing.mts' ||
          node.arguments.length !== 2 ||
          literal(node.arguments[0]) !==
            '../../../.runtime/first-party-api-routes.json'
        )
          return false;
        let owner = node.parent;
        while (owner && !ts.isFunctionLike(owner)) owner = owner.parent;
        if (
          !owner ||
          !ts.isFunctionDeclaration(owner) ||
          owner.name?.text !== 'firstPartyApiDevelopmentProxies' ||
          owner.parameters.length !== 1 ||
          !ts.isIdentifier(owner.parameters[0].name) ||
          owner.parameters[0].name.text !== 'mode' ||
          owner.parameters[0].initializer ||
          !owner.body
        )
          fail();
        const guard = owner.body.statements[0];
        if (
          !guard ||
          !ts.isIfStatement(guard) ||
          guard.elseStatement ||
          !ts.isBinaryExpression(guard.expression) ||
          guard.expression.operatorToken.kind !==
            ts.SyntaxKind.ExclamationEqualsEqualsToken ||
          !ts.isIdentifier(guard.expression.left) ||
          guard.expression.left.text !== 'mode' ||
          literal(guard.expression.right) !== 'first-party' ||
          !ts.isReturnStatement(guard.thenStatement) ||
          !guard.thenStatement.expression ||
          !ts.isObjectLiteralExpression(guard.thenStatement.expression) ||
          guard.thenStatement.expression.properties.length
        )
          fail();
        // Existing launcher-owned development inventory, inaccessible to the
        // production build mode. Its owner module remains a shared input.
        return true;
      };
      const walk = (node) => {
        if (
          (ts.isImportDeclaration(node) || ts.isExportDeclaration(node)) &&
          node.moduleSpecifier
        )
          add(literal(node.moduleSpecifier), name);
        else if (ts.isImportEqualsDeclaration(node)) {
          if (!ts.isExternalModuleReference(node.moduleReference)) fail();
          add(literal(node.moduleReference.expression), name);
        } else if (ts.isImportTypeNode(node)) {
          if (!ts.isLiteralTypeNode(node.argument)) fail();
          add(literal(node.argument.literal), name);
        } else if (ts.isCallExpression(node)) {
          const callee = node.expression.getText(tree);
          if (
            node.expression.kind === ts.SyntaxKind.ImportKeyword ||
            callee === 'require'
          ) {
            if (node.arguments.length !== 1) fail();
            add(literal(node.arguments[0]), name);
          } else if (
            importMetaField(node.expression, 'glob') ||
            importMetaField(node.expression, 'globEager') ||
            (ts.isElementAccessExpression(node.expression) &&
              importMeta(node.expression.expression))
          )
            fail();
        } else if (
          ts.isNewExpression(node) &&
          ts.isIdentifier(node.expression) &&
          node.expression.text === 'URL' &&
          importMetaField(node.arguments?.[1], 'url')
        ) {
          if (!developmentRouteProjection(node))
            add(literal(node.arguments[0]), name, true);
        }
        ts.forEachChild(node, walk);
      };
      walk(tree);
    }
  }
  return [...shared].sort();
}

if (
  process.argv[1] &&
  import.meta.url === pathToFileURL(process.argv[1]).href
) {
  try {
    const input = readFileSync(0);
    if (input.length > 64 * 1024 * 1024) fail();
    process.stdout.write(JSON.stringify(sharedUiConsumers(JSON.parse(input))));
  } catch {
    process.stderr.write(
      'Cannot prove portal frontend ownership; use a coordinated full release.\n',
    );
    process.exitCode = 1;
  }
}
