module.exports = {
  apps: [
    {
      name: "nshop-macro-daemon",
      script: "daemon.py",
      interpreter: "python3",
      cwd: __dirname,
      autorestart: true,
      watch: false,
      max_memory_restart: "1G",
      kill_timeout: 10000,
      restart_delay: 5000,
      env: {
        NODE_ENV: "production",
        PYTHONUNBUFFERED: "1"
      }
    }
  ]
};
