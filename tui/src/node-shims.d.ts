declare const process: {
  argv: string[];
  cwd(): string;
  env: Record<string, string | undefined>;
  exit(code?: number): never;
  on(event: string, listener: (...args: unknown[]) => void): void;
  stdout: {
    isTTY?: boolean;
    columns?: number;
    rows?: number;
    write(chunk: string): void;
    on(event: string, listener: (...args: unknown[]) => void): void;
    off(event: string, listener: (...args: unknown[]) => void): void;
  };
  stderr: {
    write(chunk: string): void;
  };
  stdin: {
    isTTY?: boolean;
    setRawMode(mode: boolean): void;
    setEncoding(encoding: string): void;
    resume(): void;
    on(event: string, listener: (...args: unknown[]) => void): void;
    off(event: string, listener: (...args: unknown[]) => void): void;
  };
};

type Buffer = {
  length: number;
  [index: number]: number;
  copy(target: Buffer, targetStart?: number): number;
  indexOf(value: string): number;
  slice(start?: number, end?: number): Buffer;
  toString(encoding?: string): string;
  readUInt16BE(offset: number): number;
  readBigUInt64BE(offset: number): bigint;
  writeUInt16BE(value: number, offset: number): number;
  writeBigUInt64BE(value: bigint, offset: number): number;
};

declare module "node:child_process" {
  export type ChildProcess = {
    kill(signal?: string): boolean;
    on(event: string, listener: (...args: unknown[]) => void): void;
    stderr?: { on(event: string, listener: (chunk: Uint8Array) => void): void };
    stdout?: { on(event: string, listener: (chunk: Uint8Array) => void): void };
  };

  export function spawn(command: string, args?: string[], options?: Record<string, unknown>): ChildProcess;
}

declare module "node:crypto" {
  export function randomBytes(size: number): Buffer;
  export function createHash(algorithm: string): {
    update(data: string): { digest(encoding: "base64"): string };
  };
}

declare module "node:buffer" {
  export const Buffer: {
    alloc(size: number): Buffer;
    concat(chunks: Buffer[]): Buffer;
    from(data: string | Buffer, encoding?: string): Buffer;
  };
}

declare module "node:fs" {
  export function readFileSync(path: string, encoding: "utf8"): string;
}

declare module "node:path" {
  export function join(...paths: string[]): string;
}

declare module "node:net" {
  export type Socket = {
    write(chunk: string | Buffer): void;
    end(): void;
    destroy(): void;
    once(event: string, listener: (...args: never[]) => void): void;
    on(event: string, listener: (...args: never[]) => void): void;
  };

  export function createConnection(options: { host: string; port: number }): Socket;
}

declare module "node:readline/promises" {
  export type Interface = {
    question(query: string): Promise<string>;
    close(): void;
  };

  export function createInterface(options: Record<string, unknown>): Interface;
}

declare module "node:readline" {
  export function emitKeypressEvents(stream: unknown): void;
}
