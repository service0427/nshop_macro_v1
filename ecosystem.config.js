module.exports = {
  apps: [
    {
      name: "nshop-macro-daemon",
      script: "daemon.py",
      args: "--interval 30 --until 23:50 --device-cooldown 86400 --fail-cooldown 3600 --dispatch-interval 3600 --batch-size 21 --stagger 2",
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
