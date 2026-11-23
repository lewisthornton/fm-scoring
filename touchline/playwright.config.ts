import {defineConfig} from "@playwright/test";
import {mkdtempSync} from "node:fs";
import {tmpdir} from "node:os";
import {join} from "node:path";
process.env.TOUCHLINE_FIXTURE_DIR ||= mkdtempSync(join(tmpdir(),"touchline-browser-"));
export default defineConfig({
  testDir:"browser", workers:1, timeout:90000,
  use:{baseURL:"http://127.0.0.1:8765"},
  projects: [
    {name:"chromium",use:{browserName:"chromium",launchOptions:process.env.CHROMIUM_PATH?{executablePath:process.env.CHROMIUM_PATH}:{}}},
    {name:"firefox",use:{browserName:"firefox"}},
    {name:"webkit",use:{browserName:"webkit"}}
  ],
  reporter:"list",
  webServer: {command:"python ../tests/touchline_preview.py", url:"http://127.0.0.1:8765/", timeout:90000, reuseExistingServer:false}
});
