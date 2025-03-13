// SPDX-License-Identifier: GPL-2.0-or-later

pragma solidity ^0.8.24;

import {console} from "forge-std/Test.sol";
import {Script} from "forge-std/Script.sol";

import {IEVault, IERC20, ILiquidation, IBorrowing, IERC4626, IRiskManager} from "../contracts/IEVault.sol";
import {IEVC} from "../contracts/IEVC.sol";

contract IdleLiquidation is Script {
    address constant USDC_VAULT = 0x166d8B62E1748D04eDf39d0078F1Fe4aA01D475E;
    address constant USDC = 0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48;

    address constant IDLE_VAULT = 0xd820C8129a853a04dC7e42C64aE62509f531eE5A;
    address constant IDLE_ASSET = 0x45054c6753b4Bce40C5d54418DabC20b070F85bE;

    address constant EVC_ADDRESS = 0x0C9a3dd6b8F28529d72d7f9cE918D493519EE383;

    address constant VIOLATOR = 0xe0e6111985A78E99596FE8100c07Ba8a8403060F;

    IEVault usdc_vault;
    IEVault idle_vault;

    IERC20 usdc;
    IERC20 idle;

    IEVC evc;

    function run() public {
        uint256 liquidatorPrivateKey = vm.envUint("LIQUIDATOR_PRIVATE_KEY");
        
        evc = IEVC(EVC_ADDRESS);

        usdc_vault = IEVault(USDC_VAULT);
        usdc = IERC20(USDC);

        idle_vault = IEVault(IDLE_VAULT);
        idle = IERC20(IDLE_ASSET);

        vm.startBroadcast(liquidatorPrivateKey);

        usdc.approve(USDC_VAULT, type(uint256).max);

        evc.enableController(USDC_VAULT, USDC_VAULT);
        evc.enableCollateral(IDLE_VAULT, IDLE_VAULT);

        (uint256 maxRepay, ) = usdc_vault.checkLiquidation(msg.sender, VIOLATOR, IDLE_VAULT);

        IEVC.BatchItem[] memory batchItems = new IEVC.BatchItem[](3);

        batchItems[0] = IEVC.BatchItem({
            onBehalfOfAccount: msg.sender,
            targetContract: USDC_VAULT,
            value: 0,
            data: abi.encodeCall(
                ILiquidation.liquidate,
                (VIOLATOR, IDLE_VAULT, maxRepay, 0)
            )
        });

        batchItems[1] = IEVC.BatchItem({
            onBehalfOfAccount: msg.sender,
            targetContract: USDC_VAULT,
            value: 0,
            data: abi.encodeCall(IBorrowing.repay, (maxRepay, msg.sender))
        });

        batchItems[2] = IEVC.BatchItem({
            onBehalfOfAccount: msg.sender,
            targetContract: USDC_VAULT,
            value: 0,
            data: abi.encodeCall(IRiskManager.disableController, ())
        });

        evc.batch(batchItems);
    }
}
